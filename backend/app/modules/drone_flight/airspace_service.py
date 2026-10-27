"""
Airspace Restriction Service
=============================
Single source of truth for government-regulated airspace zones in India.

Responsibilities:
  - Define all restricted zone data (airports, sensitive sites, border buffers)
  - Check whether a point (lat/lon) falls inside a restricted zone
  - Check whether a geofence polygon encloses a restricted zone center
  - Return structured violation reports used by the router (422 guard)
    and MissionValidator (validation errors)

Zone types:
  RED    — no-fly; Central Government permission required
  YELLOW — controlled; ATC / competent authority permission required

Sources:
  DigitalSky airspace map (DGCA / AAI / Ministry of Civil Aviation)
  PIB release on Drone Rules 2021 airspace classification
"""
import math
from dataclasses import dataclass
from typing import Optional


# ══════════════════════════════════════════════════════════════════
# Data model
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AirspaceViolation:
    label: str        # e.g. "Waypoint 3" or "Geofence vertex 2"
    zone_name: str    # human-readable zone name
    zone_kind: str    # "red" | "yellow" | "sensitive"
    message: str      # full user-facing message


@dataclass(frozen=True)
class AirspaceCheckResult:
    violations: list[AirspaceViolation]

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0

    @property
    def error_messages(self) -> list[str]:
        return [v.message for v in self.violations]


# ══════════════════════════════════════════════════════════════════
# Zone data
# ══════════════════════════════════════════════════════════════════

# (lat, lon, red_radius_m, yellow_radius_m, name)
# MUST stay in sync with AIRPORTS in frontend/src/utils/regulatoryZones.ts
# (same airports, same coordinates, same 5 km red / 12 km outer yellow buffers).
AIRPORT_ZONES: list[tuple[float, float, float, float, str]] = [
    (23.8869, 91.2404, 5_000, 12_000, "Agartala Maharaja Bir Bikram Airport"),
    (27.1558, 77.9609, 5_000, 12_000, "Agra Airport"),
    (31.7096, 74.7973, 5_000, 12_000, "Amritsar Sri Guru Ram Dass Jee Airport"),
    (28.5562, 77.1, 5_000, 12_000, "Delhi IGI Airport"),
    (19.0886, 72.8679, 5_000, 12_000, "Mumbai CSMIA Airport"),
    (17.2403, 78.4294, 5_000, 12_000, "Hyderabad RGIA Airport"),
    (13.1986, 77.7066, 5_000, 12_000, "Bengaluru Kempegowda International Airport"),
    (12.9941, 80.1709, 5_000, 12_000, "Chennai International Airport"),
    (22.6547, 88.4467, 5_000, 12_000, "Kolkata NSCBI Airport"),
    (23.0734, 72.6266, 5_000, 12_000, "Ahmedabad Sardar Vallabhbhai Patel International Airport (SVPI)"),
    (19.8627, 75.3981, 5_000, 12_000, "Aurangabad Airport"),
    (26.6812, 88.3286, 5_000, 12_000, "Bagdogra Airport"),
    (28.4221, 79.4508, 5_000, 12_000, "Bareilly Airport"),
    (15.8593, 74.6183, 5_000, 12_000, "Belagavi Airport"),
    (23.2875, 77.3374, 5_000, 12_000, "Bhopal Raja Bhoj Airport"),
    (20.2444, 85.8178, 5_000, 12_000, "Bhubaneswar Biju Patnaik Airport"),
    (23.2878, 69.6702, 5_000, 12_000, "Bhuj Airport"),
    (28.0706, 73.2072, 5_000, 12_000, "Bikaner Nal Airport"),
    (30.6735, 76.7885, 5_000, 12_000, "Chandigarh Airport"),
    (11.03, 77.0434, 5_000, 12_000, "Coimbatore International Airport"),
    (26.194, 85.916, 5_000, 12_000, "Darbhanga Airport"),
    (30.1897, 78.1803, 5_000, 12_000, "Dehradun Jolly Grant Airport"),
    (24.446, 86.705, 5_000, 12_000, "Deoghar Airport"),
    (27.4839, 95.0169, 5_000, 12_000, "Dibrugarh Airport"),
    (25.8839, 93.7711, 5_000, 12_000, "Dimapur Airport"),
    (20.7131, 70.9211, 5_000, 12_000, "Diu Airport"),
    (24.7443, 84.9512, 5_000, 12_000, "Gaya Airport"),
    (15.3808, 73.8314, 5_000, 12_000, "Goa Dabolim Airport"),
    (15.7443, 73.8606, 5_000, 12_000, "Goa Manohar International Airport Mopa"),
    (26.7397, 83.4497, 5_000, 12_000, "Gorakhpur Airport"),
    (26.1061, 91.5859, 5_000, 12_000, "Guwahati Lokpriya Gopinath Bordoloi Airport"),
    (26.2933, 78.2278, 5_000, 12_000, "Gwalior Airport"),
    (28.7077, 77.3589, 5_000, 12_000, "Hindon Airport"),
    (15.3617, 75.0849, 5_000, 12_000, "Hubballi Airport"),
    (24.76, 93.8967, 5_000, 12_000, "Imphal Bir Tikendrajit Airport"),
    (22.7218, 75.8011, 5_000, 12_000, "Indore Devi Ahilya Bai Holkar Airport"),
    (26.966, 93.74, 5_000, 12_000, "Itanagar Donyi Polo Airport"),
    (23.1778, 80.052, 5_000, 12_000, "Jabalpur Airport"),
    (32.6891, 74.8374, 5_000, 12_000, "Jammu Airport"),
    (22.4655, 70.0126, 5_000, 12_000, "Jamnagar Airport"),
    (26.7315, 94.1755, 5_000, 12_000, "Jorhat Airport"),
    (26.2511, 73.0489, 5_000, 12_000, "Jodhpur Airport"),
    (14.51, 78.7728, 5_000, 12_000, "Kadapa Airport"),
    (23.1127, 70.1003, 5_000, 12_000, "Kandla Airport"),
    (11.9186, 75.5472, 5_000, 12_000, "Kannur International Airport"),
    (26.4043, 80.4101, 5_000, 12_000, "Kanpur Airport"),
    (10.152, 76.4019, 5_000, 12_000, "Cochin International Airport"),
    (16.6647, 74.2894, 5_000, 12_000, "Kolhapur Airport"),
    (11.1368, 75.9553, 5_000, 12_000, "Kozhikode Calicut Airport"),
    (34.1359, 77.5465, 5_000, 12_000, "Leh Kushok Bakula Rimpochee Airport"),
    (26.8242, 75.8122, 5_000, 12_000, "Jaipur International Airport"),
    (9.8345, 78.0934, 5_000, 12_000, "Madurai Airport"),
    (12.9613, 74.8901, 5_000, 12_000, "Mangaluru International Airport"),
    (12.23, 76.6558, 5_000, 12_000, "Mysuru Airport"),
    (21.0922, 79.0472, 5_000, 12_000, "Nagpur Dr Babasaheb Ambedkar Airport"),
    (20.1191, 73.9129, 5_000, 12_000, "Nashik Airport"),
    (27.227, 88.587, 5_000, 12_000, "Pakyong Airport"),
    (25.5913, 85.0879, 5_000, 12_000, "Patna Jay Prakash Narayan Airport"),
    (21.6487, 69.6572, 5_000, 12_000, "Porbandar Airport"),
    (11.6412, 92.7297, 5_000, 12_000, "Port Blair Veer Savarkar Airport"),
    (25.4401, 81.7339, 5_000, 12_000, "Prayagraj Airport"),
    (18.5821, 73.9197, 5_000, 12_000, "Pune Airport"),
    (21.1804, 81.7388, 5_000, 12_000, "Raipur Swami Vivekananda Airport"),
    (17.1104, 81.8182, 5_000, 12_000, "Rajahmundry Airport"),
    (22.3092, 70.7795, 5_000, 12_000, "Rajkot Airport"),
    (23.3143, 85.3217, 5_000, 12_000, "Ranchi Birsa Munda Airport"),
    (11.7833, 78.0656, 5_000, 12_000, "Salem Airport"),
    (25.7036, 91.9787, 5_000, 12_000, "Shillong Airport"),
    (19.6886, 74.3789, 5_000, 12_000, "Shirdi Airport"),
    (24.9129, 92.9787, 5_000, 12_000, "Silchar Airport"),
    (33.9871, 74.7742, 5_000, 12_000, "Srinagar Airport"),
    (21.1141, 72.7418, 5_000, 12_000, "Surat Airport"),
    (26.7091, 92.7847, 5_000, 12_000, "Tezpur Airport"),
    (8.4821, 76.9201, 5_000, 12_000, "Thiruvananthapuram Airport"),
    (10.7654, 78.7097, 5_000, 12_000, "Tiruchirappalli Airport"),
    (13.6325, 79.5433, 5_000, 12_000, "Tirupati Airport"),
    (8.7242, 78.0258, 5_000, 12_000, "Tuticorin Airport"),
    (24.6177, 73.8961, 5_000, 12_000, "Udaipur Maharana Pratap Airport"),
    (22.3362, 73.2263, 5_000, 12_000, "Vadodara Airport"),
    (25.4524, 82.8593, 5_000, 12_000, "Varanasi Lal Bahadur Shastri Airport"),
    (16.5304, 80.7968, 5_000, 12_000, "Vijayawada Airport"),
    (17.7212, 83.2245, 5_000, 12_000, "Visakhapatnam Airport"),
    (26.761, 80.8893, 5_000, 12_000, "Lucknow CCS Airport"),
    (17.6272, 78.4034, 5_000, 12_000, "Dundigal Air Force Academy / AFS"),
    (21.9884, 82.111, 5_000, 12_000, "Bilaspur Airport (Chhattisgarh)"),
    (21.7522, 72.1852, 5_000, 12_000, "Bhavnagar Airport"),
    (14.1493, 77.7911, 5_000, 12_000, "Sri Sathya Sai Airport Puttaparthi"),
    (12.95, 77.6682, 5_000, 12_000, "HAL Airport Bengaluru"),
    (19.1833, 77.3167, 5_000, 12_000, "Nanded Airport"),
    (22.3788, 71.0394, 5_000, 12_000, "Rajkot International Airport (Hirasar)"),
    (18.2269, 74.5908, 5_000, 12_000, "Baramati Airport"),
    (26.7477, 82.1637, 5_000, 12_000, "Ayodhya Maharishi Valmiki International Airport"),
    (20.8146, 77.7178, 5_000, 12_000, "Amravati Airport"),
    (16.0026, 73.5298, 5_000, 12_000, "Sindhudurg Chipi Airport"),
    (18.9846, 73.0652, 5_000, 12_000, "Navi Mumbai International Airport"),
    (13.858, 75.6189, 5_000, 12_000, "Shivamogga Rashtrakavi Kuvempu Airport"),
    (26.9668, 93.6388, 5_000, 12_000, "Itanagar Donyi Polo Hollongi Airport"),
    (25.5912, 84.8831, 5_000, 12_000, "Bihta Air Force Station"),
    (20.3958, 78.2163, 5_000, 12_000, "Yavatmal Sant Gadge Baba Airport"),
    (28.1799, 77.6118, 5_000, 12_000, "Noida International Airport (Jewar)"),
    (22.9875, 83.1961, 5_000, 12_000, "Ambikapur Maa Mahamaya Airport"),
    (19.0743, 82.0368, 5_000, 12_000, "Jagdalpur Airport"),
    (24.5034, 81.2203, 5_000, 12_000, "Rewa Airport"),
    (23.2223, 68.8913, 5_000, 12_000, "Naliya Air Force Station"),
    (21.5268, 80.2903, 5_000, 12_000, "Gondia Airport"),
    (20.6989, 77.0569, 5_000, 12_000, "Akola Airport"),
    (20.4344, 72.8432, 5_000, 12_000, "Daman Airport"),
    (20.9627, 75.6275, 5_000, 12_000, "Jalgaon Airport"),
    (24.8172, 79.9186, 5_000, 12_000, "Khajuraho Airport"),
    (21.3171, 70.2704, 5_000, 12_000, "Keshod Airport"),
    (18.4115, 76.4647, 5_000, 12_000, "Latur Murod Kond Airport"),
    (17.0136, 73.3278, 5_000, 12_000, "Ratnagiri Airport"),
    (17.628, 75.9348, 5_000, 12_000, "Solapur Airport"),
    (20.5496, 85.8863, 5_000, 12_000, "Cuttack Charbatia Air Force Station"),
    (28.1753, 94.802, 5_000, 12_000, "Along Airport"),
    (27.4622, 95.1177, 5_000, 12_000, "Chabua Air Force Station"),
    (23.834, 86.4253, 5_000, 12_000, "Dhanbad Airport"),
    (23.6225, 87.243, 5_000, 12_000, "Durgapur Kazi Nazrul Islam Airport"),
    (22.3395, 87.2145, 5_000, 12_000, "Kalaikunda Air Force Station (Kharagpur)"),
    (26.6983, 89.3691, 5_000, 12_000, "Hashimara Air Force Station"),
    (21.9135, 84.0504, 5_000, 12_000, "Jharsuguda Airport"),
    (22.8137, 86.169, 5_000, 12_000, "Jamshedpur Sonari Airport"),
    (26.7765, 83.8892, 5_000, 12_000, "Kushinagar International Airport"),
    (24.3087, 92.0077, 5_000, 12_000, "Kailashahar Airport"),
    (23.8406, 92.6197, 5_000, 12_000, "Aizawl Lengpui Airport"),
    (27.2957, 94.0973, 5_000, 12_000, "Lilabari North Lakhimpur Airport"),
    (26.1191, 85.3137, 5_000, 12_000, "Muzaffarpur Airport"),
    (23.4743, 87.4275, 5_000, 12_000, "Panagarh Air Force Station"),
    (22.781, 88.3592, 5_000, 12_000, "Barrackpore Air Force Station"),
    (22.2566, 84.8152, 5_000, 12_000, "Rourkela Airport"),
    (20.0978, 83.1833, 5_000, 12_000, "Utkela Airport"),
    (27.5883, 93.8281, 5_000, 12_000, "Ziro Airport"),
    (30.3681, 76.8167, 5_000, 12_000, "Ambala Air Force Station"),
    (33.8766, 74.9757, 5_000, 12_000, "Awantipura Air Force Station"),
    (31.4338, 75.7588, 5_000, 12_000, "Adampur Airport"),
    (26.9883, 80.8931, 5_000, 12_000, "Bakshi Ka Talab Air Force Station (Lucknow)"),
    (31.8767, 77.1544, 5_000, 12_000, "Kullu Manali Airport (Bhuntar)"),
    (30.2701, 74.7558, 5_000, 12_000, "Bhatinda Air Force Station"),
    (28.5855, 77.2036, 5_000, 12_000, "Safdarjung Airport (New Delhi)"),
    (32.1649, 76.263, 5_000, 12_000, "Kangra Gaggal Airport (Dharamshala)"),
    (29.1861, 75.7414, 5_000, 12_000, "Hisar Maharaja Agrasen International Airport"),
    (30.7485, 75.6298, 5_000, 12_000, "Halwara International Airport"),
    (26.8887, 70.865, 5_000, 12_000, "Jaisalmer Airport"),
    (26.591, 74.813, 5_000, 12_000, "Kishangarh Ajmer Airport"),
    (25.1602, 75.8456, 5_000, 12_000, "Kota Airport"),
    (30.8547, 75.9526, 5_000, 12_000, "Ludhiana Airport"),
    (28.8175, 78.9219, 5_000, 12_000, "Moradabad Airport"),
    (32.2336, 75.6344, 5_000, 12_000, "Pathankot Airport"),
    (29.0334, 79.4737, 5_000, 12_000, "Pantnagar Airport"),
    (27.1049, 72.2129, 5_000, 12_000, "Phalodi Air Force Station"),
    (29.5606, 75.0061, 5_000, 12_000, "Sirsa Air Force Station"),
    (29.9943, 77.4246, 5_000, 12_000, "Sarsawa Air Force Station"),
    (27.4997, 82.0329, 5_000, 12_000, "Shravasti Airport"),
    (32.9022, 75.1557, 5_000, 12_000, "Udhampur Air Force Station"),
    (7.013, 93.9228, 5_000, 12_000, "Campbell Bay Airport / INS Baaz"),
    (13.0712, 79.6912, 5_000, 12_000, "Arakkonam INS Rajali Naval Air Station"),
    (10.8237, 72.176, 5_000, 12_000, "Agatti Airport"),
    (15.1628, 76.8828, 5_000, 12_000, "Bellary Airport"),
    (17.9081, 77.4871, 5_000, 12_000, "Bidar Air Force Station"),
    (9.9461, 76.2719, 5_000, 12_000, "Kochi INS Garuda Naval Air Station"),
    (9.1531, 92.8193, 5_000, 12_000, "Car Nicobar Air Force Base"),
    (17.3082, 76.9652, 5_000, 12_000, "Kalaburagi Airport"),
    (17.4531, 78.4676, 5_000, 12_000, "Hyderabad Begumpet Airport"),
    (15.7163, 78.1692, 5_000, 12_000, "Kurnool Orvakal Airport"),
    (11.968, 79.812, 5_000, 12_000, "Puducherry Airport"),
    (9.3251, 78.9715, 5_000, 12_000, "Ramnad INS Parundu Naval Air Station"),
    (11.0136, 77.1597, 5_000, 12_000, "Sulur Air Force Station (Coimbatore)"),
    (10.7238, 79.1095, 5_000, 12_000, "Thanjavur Air Force Station"),
    (12.9072, 80.1219, 5_000, 12_000, "Tambaram Air Force Station (Chennai)"),
    (17.9715, 83.5036, 5_000, 12_000, "Alluri Sitarama Raju International Airport (Bhogapuram)"),
    (13.1355, 77.606, 5_000, 12_000, "Yelahanka Air Force Station (Bengaluru)"),
]

# (lat, lon, radius_m, name)
SENSITIVE_ZONES: list[tuple[float, float, float, str]] = [
    (28.6143, 77.1999, 3_000, "Central Delhi high-security zone"),
    (18.9420, 72.8430, 3_000, "Mumbai naval dockyard / port zone"),
]


# ══════════════════════════════════════════════════════════════════
# Geometry helpers
# ══════════════════════════════════════════════════════════════════

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points in metres."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _segment_min_distance_m(
    alat: float, alon: float,
    blat: float, blon: float,
    plat: float, plon: float,
) -> float:
    """
    Minimum distance in metres from point P to the line segment A→B.
    Projects everything into a local flat-Earth coordinate system
    centred on the midpoint of AB (accurate enough for segments < 200 km).
    """
    ref_lat = (alat + blat + plat) / 3
    scale_lat = 111_320.0
    scale_lon = 111_320.0 * math.cos(math.radians(ref_lat))

    ax, ay = alon * scale_lon, alat * scale_lat
    bx, by = blon * scale_lon, blat * scale_lat
    px, py = plon * scale_lon, plat * scale_lat

    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq == 0:
        return math.hypot(px - ax, py - ay)

    # Parameter t: projection of P onto the infinite line through A and B
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    closest_x = ax + t * dx
    closest_y = ay + t * dy
    return math.hypot(px - closest_x, py - closest_y)


def _point_in_polygon(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test. Ring is [(lat, lon), ...]."""
    inside = False
    n = len(ring)
    for i in range(n):
        j = (i - 1) % n
        yi, xi = ring[i]
        yj, xj = ring[j]
        if ((yi > lat) != (yj > lat)) and \
                (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
    return inside


def _geojson_to_ring(geofence: dict) -> Optional[list[tuple[float, float]]]:
    """
    Extract the outer ring from a GeoJSON Polygon as [(lat, lon), ...].
    Skips the closing duplicate vertex.
    Returns None if the geometry is invalid.
    """
    try:
        coords = geofence.get("coordinates", [])
        if not coords or not isinstance(coords[0], list):
            return None
        ring = coords[0]
        # GeoJSON is [lon, lat]; drop the closing repeat
        return [(pt[1], pt[0]) for pt in ring[:-1]]
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════

def check_points(
    points: list[tuple[float, float, str]],
) -> list[AirspaceViolation]:
    """
    Check a list of (lat, lon, label) points against all restricted zones.
    Returns one AirspaceViolation per violation found.
    """
    violations: list[AirspaceViolation] = []
    for lat, lon, label in points:
        for alat, alon, red_m, yellow_m, aname in AIRPORT_ZONES:
            dist = _haversine_m(lat, lon, alat, alon)
            if dist <= red_m:
                violations.append(AirspaceViolation(
                    label=label,
                    zone_name=aname,
                    zone_kind="red",
                    message=(
                        f"{label} is inside the red no-fly zone (0–5 km) of {aname}. "
                        f"Central Government permission required."
                    ),
                ))
            elif dist <= yellow_m:
                violations.append(AirspaceViolation(
                    label=label,
                    zone_name=aname,
                    zone_kind="yellow",
                    message=(
                        f"{label} is inside the controlled yellow zone (5–12 km) of {aname}. "
                        f"ATC / competent authority permission required."
                    ),
                ))
        for slat, slon, radius_m, sname in SENSITIVE_ZONES:
            dist = _haversine_m(lat, lon, slat, slon)
            if dist <= radius_m:
                violations.append(AirspaceViolation(
                    label=label,
                    zone_name=sname,
                    zone_kind="sensitive",
                    message=(
                        f"{label} is inside the restricted zone of {sname}. "
                        f"No-drone operation without Central Government permission."
                    ),
                ))
    return violations


def check_geofence_encloses(
    ring: list[tuple[float, float]],
) -> list[AirspaceViolation]:
    """
    Check whether a geofence polygon (ring of lat/lon pairs) encloses
    the centre of any restricted zone.
    A polygon can legally surround an airport even when no vertex touches it.
    """
    if len(ring) < 3:
        return []

    violations: list[AirspaceViolation] = []
    for alat, alon, _red, _yellow, aname in AIRPORT_ZONES:
        if _point_in_polygon(alat, alon, ring):
            violations.append(AirspaceViolation(
                label="Geofence",
                zone_name=aname,
                zone_kind="red",
                message=(
                    f"Geofence polygon encloses {aname} (restricted airspace). "
                    f"Redraw the geofence to exclude all airport zones."
                ),
            ))
    for slat, slon, _radius, sname in SENSITIVE_ZONES:
        if _point_in_polygon(slat, slon, ring):
            violations.append(AirspaceViolation(
                label="Geofence",
                zone_name=sname,
                zone_kind="sensitive",
                message=(
                    f"Geofence polygon encloses {sname} (restricted area). "
                    f"Redraw the geofence to exclude all restricted zones."
                ),
            ))
    return violations


def check_geofence_edges(
    ring: list[tuple[float, float]],
) -> list[AirspaceViolation]:
    """
    Check whether any edge (line segment between consecutive vertices) of the
    geofence polygon crosses through a restricted zone circle.

    This catches the case where vertices are all outside a zone but the straight
    line between two of them passes through it (e.g. a geofence side clipping
    the edge of an airport red/yellow ring).
    """
    if len(ring) < 2:
        return []

    seen: set[str] = set()   # avoid duplicate violations for the same zone + edge pair
    violations: list[AirspaceViolation] = []
    n = len(ring)

    for i in range(n):
        alat, alon = ring[i]
        blat, blon = ring[(i + 1) % n]
        edge_label = f"Geofence edge {i + 1}–{(i + 1) % n + 1}"

        for zlat, zlon, red_m, yellow_m, zname in AIRPORT_ZONES:
            dist = _segment_min_distance_m(alat, alon, blat, blon, zlat, zlon)
            key_red    = f"{zname}:red:{i}"
            key_yellow = f"{zname}:yellow:{i}"
            if dist <= red_m and key_red not in seen:
                seen.add(key_red)
                violations.append(AirspaceViolation(
                    label=edge_label,
                    zone_name=zname,
                    zone_kind="red",
                    message=(
                        f"{edge_label} crosses through the red no-fly zone (0–5 km) of {zname}. "
                        f"Redraw the geofence to avoid all restricted zones."
                    ),
                ))
            elif dist <= yellow_m and key_yellow not in seen:
                seen.add(key_yellow)
                violations.append(AirspaceViolation(
                    label=edge_label,
                    zone_name=zname,
                    zone_kind="yellow",
                    message=(
                        f"{edge_label} crosses through the controlled yellow zone (5–12 km) of {zname}. "
                        f"Redraw the geofence to avoid all restricted zones."
                    ),
                ))

        for zlat, zlon, radius_m, zname in SENSITIVE_ZONES:
            dist = _segment_min_distance_m(alat, alon, blat, blon, zlat, zlon)
            key = f"{zname}:sensitive:{i}"
            if dist <= radius_m and key not in seen:
                seen.add(key)
                violations.append(AirspaceViolation(
                    label=edge_label,
                    zone_name=zname,
                    zone_kind="sensitive",
                    message=(
                        f"{edge_label} crosses through the restricted zone of {zname}. "
                        f"Redraw the geofence to avoid all restricted zones."
                    ),
                ))

    return violations


def check_waypoint_edges(
    points: list[tuple[float, float, str]],
) -> list[AirspaceViolation]:
    """
    Check whether any mission leg between consecutive waypoints touches or
    crosses a restricted zone circle.

    This catches paths where both endpoint waypoints are outside a zone but the
    straight flight segment between them clips or passes through it.
    """
    if len(points) < 2:
        return []

    seen: set[str] = set()
    violations: list[AirspaceViolation] = []

    for i in range(len(points) - 1):
        alat, alon, alabel = points[i]
        blat, blon, blabel = points[i + 1]
        leg_label = f"Mission leg {alabel} to {blabel}"

        for zlat, zlon, red_m, yellow_m, zname in AIRPORT_ZONES:
            dist = _segment_min_distance_m(alat, alon, blat, blon, zlat, zlon)
            key_red = f"{zname}:red:{i}"
            key_yellow = f"{zname}:yellow:{i}"
            if dist <= red_m and key_red not in seen:
                seen.add(key_red)
                violations.append(AirspaceViolation(
                    label=leg_label,
                    zone_name=zname,
                    zone_kind="red",
                    message=(
                        f"{leg_label} touches or crosses the red no-fly zone "
                        f"(0-5 km) of {zname}. Move the waypoints to avoid all "
                        f"restricted zones."
                    ),
                ))
            elif dist <= yellow_m and key_yellow not in seen:
                seen.add(key_yellow)
                violations.append(AirspaceViolation(
                    label=leg_label,
                    zone_name=zname,
                    zone_kind="yellow",
                    message=(
                        f"{leg_label} touches or crosses the controlled yellow zone "
                        f"(5-12 km) of {zname}. Move the waypoints to avoid all "
                        f"restricted zones."
                    ),
                ))

        for zlat, zlon, radius_m, zname in SENSITIVE_ZONES:
            dist = _segment_min_distance_m(alat, alon, blat, blon, zlat, zlon)
            key = f"{zname}:sensitive:{i}"
            if dist <= radius_m and key not in seen:
                seen.add(key)
                violations.append(AirspaceViolation(
                    label=leg_label,
                    zone_name=zname,
                    zone_kind="sensitive",
                    message=(
                        f"{leg_label} touches or crosses the restricted zone of "
                        f"{zname}. Move the waypoints to avoid all restricted zones."
                    ),
                ))

    return violations


def validate_mission_airspace(
    waypoints: list[tuple[float, float, str]],
    geofence: Optional[dict] = None,
) -> AirspaceCheckResult:
    """
    Full airspace check for a mission:
      1. Each waypoint must not be inside a restricted zone.
      2. Each geofence vertex must not be inside a restricted zone.
      3. Each geofence edge must not cross through a restricted zone.
      4. The geofence polygon must not enclose a restricted zone centre.

    Args:
        waypoints: list of (lat, lon, label)
        geofence:  GeoJSON Polygon dict, or None

    Returns:
        AirspaceCheckResult — call .ok, .error_messages
    """
    violations: list[AirspaceViolation] = []

    # 1. Waypoint point checks
    violations.extend(check_points(waypoints))

    # 1b. Waypoint leg checks
    violations.extend(check_waypoint_edges(waypoints))

    if geofence:
        ring = _geojson_to_ring(geofence)
        if ring:
            # 2. Geofence vertex point checks
            vertex_points = [
                (lat, lon, f"Geofence vertex {i + 1}")
                for i, (lat, lon) in enumerate(ring)
            ]
            violations.extend(check_points(vertex_points))

            # 3. Geofence edge intersection checks
            violations.extend(check_geofence_edges(ring))

            # 4. Polygon-encloses-zone-centre check
            violations.extend(check_geofence_encloses(ring))

    return AirspaceCheckResult(violations=violations)
