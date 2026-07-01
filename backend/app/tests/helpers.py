from uuid import uuid4


def auth_headers(user, make_token) -> dict[str, str]:
    token = make_token(user.id, user.role)
    return {"Authorization": f"Bearer {token}"}


def suffix() -> str:
    return uuid4().hex[:8]


def drone_type_payload(name: str | None = None, **overrides) -> dict:
    tag = suffix()
    data = {
        "name": name or f"Scout-{tag}",
        "manufacturer": "Arjuna Labs",
        "model": f"AL-{tag}",
        "size_class": "small",
        "mission_type": "ISR",
        "is_vtol": True,
        "max_speed_ms": 30.0,
        "cruise_speed_ms": 18.0,
        "max_altitude_m": 500.0,
        "endurance_h": 2.0,
        "range_km": 80.0,
        "max_takeoff_weight_kg": 12.0,
        "max_payload_weight_kg": 3.0,
        "autopilot_type": "PX4",
        "notes": "Test drone type",
    }
    data.update(overrides)
    return data


def drone_instance_payload(type_id: int, call_sign: str | None = None, **overrides) -> dict:
    tag = suffix()
    data = {
        "call_sign": call_sign or f"da-{tag}",
        "drone_type_id": type_id,
        "serial_number": f"SN-{tag}",
        "mavlink_system_id": 42,
        "notes": "Test drone instance",
    }
    data.update(overrides)
    return data


def vessel_payload(vessel_id: str | None = None, **overrides) -> dict:
    tag = suffix()
    data = {
        "vessel_id": vessel_id or f"ins-{tag}",
        "name": f"INS Test {tag}",
        "vessel_type": "frigate",
        "hull_number": f"H-{tag}",
        "sea_state": 2,
        "deck_status": "clear",
        "landing_spots": 2,
        "hf_modem_type": "generic",
        "hf_frequency_mhz": 8.2,
        "hf_link_encrypted": True,
        "notes": "Test vessel",
    }
    data.update(overrides)
    return data


def payload_type_payload(name: str | None = None, **overrides) -> dict:
    tag = suffix()
    data = {
        "name": name or f"EO Camera {tag}",
        "manufacturer": "Arjuna Sensors",
        "model": f"AS-CAM-{tag}",
        "category": "sensor",
        "weight_kg": 0.85,
        "voltage_v": 5.0,
        "max_current_a": 1.2,
        "has_gimbal": True,
        "sensor_type": "EO",
    }
    data.update(overrides)
    return data


def access_request_payload(username: str | None = None, **overrides) -> dict:
    tag = suffix()
    data = {
        "username": username or f"op_{tag}",
        "full_name": f"Operator {tag}",
        "email": f"op_{tag}@example.com",
        "mobile": "+91 9000000000",
        "requested_role": "viewer",
        "reason": "Joining field ops team",
    }
    data.update(overrides)
    return data


def mission_payload(drone_id: int | None = None, **overrides) -> dict:
    tag = suffix()
    data = {
        "name": f"Patrol {tag}",
        "description": "Test mission",
        "mission_type": "ISR",
        "drone_instance_id": drone_id,
        "waypoints": [
            {
                "sequence": 1,
                "latitude": 12.9000,
                "longitude": 80.1000,
                "altitude_m": 20.0,
                "altitude_ref": "AGL",
                "speed_ms": 12.0,
                "action": "none",
                "is_home": True,
            },
            {
                "sequence": 2,
                "latitude": 12.9010,
                "longitude": 80.1010,
                "altitude_m": 40.0,
                "altitude_ref": "AGL",
                "speed_ms": 12.0,
                "action": "photo",
                "is_home": False,
            },
        ],
        "notes": "Test mission",
    }
    data.update(overrides)
    return data
