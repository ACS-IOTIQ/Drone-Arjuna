export type RegulatoryZoneKind = 'red' | 'orange' | 'green'
export type RegulatoryAction = 'continue' | 'reduce' | 'hold' | 'rtl'

export interface RegulatorySource {
  name: string
  authority: string
  url: string
  checkedOn: string
  notes: string
}

export interface RegulatoryRule {
  id: string
  name: string
  kind: RegulatoryZoneKind
  action: RegulatoryAction
  authority: string
  source: RegulatorySource
  restriction: string
  maxAltitudeM: number
  maxSpeedMs: number
  recommendedAltitudeM: number
  recommendedSpeedMs: number
  requiresPermission: boolean
}

export interface RegulatoryZone {
  id: string
  name: string
  country: string
  authority: string
  kind: RegulatoryZoneKind
  source: RegulatorySource
  restriction: string
  center?: [number, number]
  polygon?: [number, number][]
  polygons?: [number, number][][]
  innerRadiusM?: number
  outerRadiusM: number
  maxAltitudeM: number
  maxSpeedMs: number
  recommendedAltitudeM: number
  recommendedSpeedMs: number
  requiresPermission: boolean
  action: RegulatoryAction
}

export interface RegulatoryZoneLayer extends RegulatoryRule {
  positions: [number, number][] | [number, number][][]
  color: string
  fillColor: string
  fillOpacity: number
}

const DIGITAL_SKY_SOURCE: RegulatorySource = {
  name: 'DigitalSky airspace map rules (offline snapshot)',
  authority: 'Ministry of Civil Aviation / DGCA / AAI',
  url: 'https://digitalsky.aai.aero/digital-sky-map',
  checkedOn: '2026-07-09',
  notes:
    'The official DigitalSky map is dynamic and requires an authenticated, internet-connected registered-operator session. DroneArjuna does not call it live; this layer is a static offline snapshot of airport red/yellow buffers derived from published DigitalSky/PIB guidance, checked on the date above. Refresh manually from official sources when connectivity and credentials are available.',
}

const PIB_SOURCE: RegulatorySource = {
  name: 'PIB release: India airspace map for drone operations',
  authority: 'Ministry of Civil Aviation',
  url: 'https://www.pib.gov.in/PressReleasePage.aspx?PRID=1757850',
  checkedOn: '2026-07-09',
  notes:
    'Defines green, yellow, and red zone semantics for drone operations under the Drone Rules, 2021.',
}

const MAPPLS_AIRSPACE_SOURCE: RegulatorySource = {
  name: 'Mappls DigitalSky airspace layer documentation',
  authority: 'Mappls / DigitalSky layer integration docs',
  url: 'https://developer.mappls.com/mapping/air-space/',
  checkedOn: '2026-07-10',
  notes:
    'Documents DigitalSky layer ids including International Boundary - 25km, Airport Red, and Airport Yellow layers. This app uses a built-in approximation unless a Mappls access token/provider feed is configured.',
}

const OFFLINE_SNAPSHOT_CHECKED_ON = '2026-07-09'

const AIRPORTS: Array<{ id: string; name: string; lat: number; lon: number }> = [
  { id: 'agartala-veat', name: 'Agartala Maharaja Bir Bikram Airport', lat: 23.8869, lon: 91.2404 },
  { id: 'agra-viag', name: 'Agra Airport', lat: 27.1558, lon: 77.9609 },
  { id: 'amritsar-viar', name: 'Amritsar Sri Guru Ram Dass Jee Airport', lat: 31.7096, lon: 74.7973 },
  { id: 'delhi-vidp', name: 'Delhi IGI Airport', lat: 28.5562, lon: 77.1000 },
  { id: 'mumbai-vabb', name: 'Mumbai CSMIA Airport', lat: 19.0886, lon: 72.8679 },
  { id: 'hyderabad-vohs', name: 'Hyderabad RGIA Airport', lat: 17.2403, lon: 78.4294 },
  { id: 'bengaluru-vobl', name: 'Bengaluru Kempegowda International Airport', lat: 13.1986, lon: 77.7066 },
  { id: 'chennai-vomm', name: 'Chennai International Airport', lat: 12.9941, lon: 80.1709 },
  { id: 'kolkata-vecc', name: 'Kolkata NSCBI Airport', lat: 22.6547, lon: 88.4467 },
  { id: 'ahmedabad-vaah', name: 'Ahmedabad Sardar Vallabhbhai Patel International Airport (SVPI)', lat: 23.0734, lon: 72.6266 },
  { id: 'aurangabad-vabb', name: 'Aurangabad Airport', lat: 19.8627, lon: 75.3981 },
  { id: 'bagdogra-vebd', name: 'Bagdogra Airport', lat: 26.6812, lon: 88.3286 },
  { id: 'bareilly-vibY', name: 'Bareilly Airport', lat: 28.4221, lon: 79.4508 },
  { id: 'belagavi-vobm', name: 'Belagavi Airport', lat: 15.8593, lon: 74.6183 },
  { id: 'bhopal-vabh', name: 'Bhopal Raja Bhoj Airport', lat: 23.2875, lon: 77.3374 },
  { id: 'bhubaneswar-vebs', name: 'Bhubaneswar Biju Patnaik Airport', lat: 20.2444, lon: 85.8178 },
  { id: 'bhuj-vabj', name: 'Bhuj Airport', lat: 23.2878, lon: 69.6702 },
  { id: 'bikaner-vibk', name: 'Bikaner Nal Airport', lat: 28.0706, lon: 73.2072 },
  { id: 'chandigarh-vicg', name: 'Chandigarh Airport', lat: 30.6735, lon: 76.7885 },
  { id: 'coimbatore-vocb', name: 'Coimbatore International Airport', lat: 11.0300, lon: 77.0434 },
  { id: 'darbhanga-vedh', name: 'Darbhanga Airport', lat: 26.1940, lon: 85.9160 },
  { id: 'dehradun-vidn', name: 'Dehradun Jolly Grant Airport', lat: 30.1897, lon: 78.1803 },
  { id: 'deoghar-vedg', name: 'Deoghar Airport', lat: 24.4460, lon: 86.7050 },
  { id: 'dibrugarh-vedb', name: 'Dibrugarh Airport', lat: 27.4839, lon: 95.0169 },
  { id: 'dimapur-vedm', name: 'Dimapur Airport', lat: 25.8839, lon: 93.7711 },
  { id: 'diu-vadi', name: 'Diu Airport', lat: 20.7131, lon: 70.9211 },
  { id: 'gaya-vegY', name: 'Gaya Airport', lat: 24.7443, lon: 84.9512 },
  { id: 'goa-vogo', name: 'Goa Dabolim Airport', lat: 15.3808, lon: 73.8314 },
  { id: 'goa-mopa-voga', name: 'Goa Manohar International Airport Mopa', lat: 15.7443, lon: 73.8606 },
  { id: 'gorakhpur-vegk', name: 'Gorakhpur Airport', lat: 26.7397, lon: 83.4497 },
  { id: 'guwahati-vegt', name: 'Guwahati Lokpriya Gopinath Bordoloi Airport', lat: 26.1061, lon: 91.5859 },
  { id: 'gwalior-vigR', name: 'Gwalior Airport', lat: 26.2933, lon: 78.2278 },
  { id: 'hindon-vidx', name: 'Hindon Airport', lat: 28.7077, lon: 77.3589 },
  { id: 'hubli-vohb', name: 'Hubballi Airport', lat: 15.3617, lon: 75.0849 },
  { id: 'imphal-veim', name: 'Imphal Bir Tikendrajit Airport', lat: 24.7600, lon: 93.8967 },
  { id: 'indore-vaid', name: 'Indore Devi Ahilya Bai Holkar Airport', lat: 22.7218, lon: 75.8011 },
  { id: 'itanagar-vezo', name: 'Itanagar Donyi Polo Airport', lat: 26.9660, lon: 93.7400 },
  { id: 'jabalpur-vajb', name: 'Jabalpur Airport', lat: 23.1778, lon: 80.0520 },
  { id: 'jammu-vijU', name: 'Jammu Airport', lat: 32.6891, lon: 74.8374 },
  { id: 'jamnagar-vajm', name: 'Jamnagar Airport', lat: 22.4655, lon: 70.0126 },
  { id: 'jorhat-vejt', name: 'Jorhat Airport', lat: 26.7315, lon: 94.1755 },
  { id: 'jodhpur-vijO', name: 'Jodhpur Airport', lat: 26.2511, lon: 73.0489 },
  { id: 'kadapa-vocp', name: 'Kadapa Airport', lat: 14.5100, lon: 78.7728 },
  { id: 'kandla-vaKE', name: 'Kandla Airport', lat: 23.1127, lon: 70.1003 },
  { id: 'kannur-vokr', name: 'Kannur International Airport', lat: 11.9186, lon: 75.5472 },
  { id: 'kanpur-vika', name: 'Kanpur Airport', lat: 26.4043, lon: 80.4101 },
  { id: 'kochi-voci', name: 'Cochin International Airport', lat: 10.1520, lon: 76.4019 },
  { id: 'kolhapur-vakp', name: 'Kolhapur Airport', lat: 16.6647, lon: 74.2894 },
  { id: 'kozhikode-vocc', name: 'Kozhikode Calicut Airport', lat: 11.1368, lon: 75.9553 },
  { id: 'leh-vilH', name: 'Leh Kushok Bakula Rimpochee Airport', lat: 34.1359, lon: 77.5465 },
  { id: 'jaipur-vijP', name: 'Jaipur International Airport', lat: 26.8242, lon: 75.8122 },
  { id: 'madurai-vomd', name: 'Madurai Airport', lat: 9.8345, lon: 78.0934 },
  { id: 'mangaluru-voml', name: 'Mangaluru International Airport', lat: 12.9613, lon: 74.8901 },
  { id: 'mysuru-vomy', name: 'Mysuru Airport', lat: 12.2300, lon: 76.6558 },
  { id: 'nagpur-vanp', name: 'Nagpur Dr Babasaheb Ambedkar Airport', lat: 21.0922, lon: 79.0472 },
  { id: 'nashik-vaoz', name: 'Nashik Airport', lat: 20.1191, lon: 73.9129 },
  { id: 'pakyong-vepy', name: 'Pakyong Airport', lat: 27.2270, lon: 88.5870 },
  { id: 'patna-vept', name: 'Patna Jay Prakash Narayan Airport', lat: 25.5913, lon: 85.0879 },
  { id: 'porbandar-vapr', name: 'Porbandar Airport', lat: 21.6487, lon: 69.6572 },
  { id: 'port-blair-vopb', name: 'Port Blair Veer Savarkar Airport', lat: 11.6412, lon: 92.7297 },
  { id: 'prayagraj-viix', name: 'Prayagraj Airport', lat: 25.4401, lon: 81.7339 },
  { id: 'pune-vapO', name: 'Pune Airport', lat: 18.5821, lon: 73.9197 },
  { id: 'raipur-verp', name: 'Raipur Swami Vivekananda Airport', lat: 21.1804, lon: 81.7388 },
  { id: 'rajahmundry-vory', name: 'Rajahmundry Airport', lat: 17.1104, lon: 81.8182 },
  { id: 'rajkot-vark', name: 'Rajkot Airport', lat: 22.3092, lon: 70.7795 },
  { id: 'ranchi-verc', name: 'Ranchi Birsa Munda Airport', lat: 23.3143, lon: 85.3217 },
  { id: 'salem-vosl', name: 'Salem Airport', lat: 11.7833, lon: 78.0656 },
  { id: 'shillong-vesh', name: 'Shillong Airport', lat: 25.7036, lon: 91.9787 },
  { id: 'shirdi-vasd', name: 'Shirdi Airport', lat: 19.6886, lon: 74.3789 },
  { id: 'silchar-vekU', name: 'Silchar Airport', lat: 24.9129, lon: 92.9787 },
  { id: 'srinagar-visR', name: 'Srinagar Airport', lat: 33.9871, lon: 74.7742 },
  { id: 'surat-vasu', name: 'Surat Airport', lat: 21.1141, lon: 72.7418 },
  { id: 'tezpur-vetz', name: 'Tezpur Airport', lat: 26.7091, lon: 92.7847 },
  { id: 'thiruvananthapuram-votv', name: 'Thiruvananthapuram Airport', lat: 8.4821, lon: 76.9201 },
  { id: 'tiruchirappalli-votr', name: 'Tiruchirappalli Airport', lat: 10.7654, lon: 78.7097 },
  { id: 'tirupati-votp', name: 'Tirupati Airport', lat: 13.6325, lon: 79.5433 },
  { id: 'tuticorin-votk', name: 'Tuticorin Airport', lat: 8.7242, lon: 78.0258 },
  { id: 'udaipur-vaud', name: 'Udaipur Maharana Pratap Airport', lat: 24.6177, lon: 73.8961 },
  { id: 'vadodara-vabO', name: 'Vadodara Airport', lat: 22.3362, lon: 73.2263 },
  { id: 'varanasi-vebn', name: 'Varanasi Lal Bahadur Shastri Airport', lat: 25.4524, lon: 82.8593 },
  { id: 'vijayawada-vobz', name: 'Vijayawada Airport', lat: 16.5304, lon: 80.7968 },
  { id: 'visakhapatnam-vevz', name: 'Visakhapatnam Airport', lat: 17.7212, lon: 83.2245 },
  { id: 'lucknow-vilK', name: 'Lucknow CCS Airport', lat: 26.7610, lon: 80.8893 },

  // Added 2026-10-27 — airports / air force stations missing from the original snapshot.
  // Coordinates from the OurAirports dataset (ARP positions). Same 5 / 8 / 12 km buffers as above.
  { id: 'dundigal-vodg', name: 'Dundigal Air Force Academy / AFS', lat: 17.6272, lon: 78.4034 },
  { id: 'bilaspur-vebu', name: 'Bilaspur Airport (Chhattisgarh)', lat: 21.9884, lon: 82.1110 },
  { id: 'bhavnagar-vabv', name: 'Bhavnagar Airport', lat: 21.7522, lon: 72.1852 },
  { id: 'puttaparthi-vopn', name: 'Sri Sathya Sai Airport Puttaparthi', lat: 14.1493, lon: 77.7911 },
  { id: 'hal-vobg', name: 'HAL Airport Bengaluru', lat: 12.9500, lon: 77.6682 },
  { id: 'nanded-vand', name: 'Nanded Airport', lat: 19.1833, lon: 77.3167 },
  { id: 'rajkot-hirasar-vahs', name: 'Rajkot International Airport (Hirasar)', lat: 22.3788, lon: 71.0394 },
  { id: 'baramati-in0024', name: 'Baramati Airport', lat: 18.2269, lon: 74.5908 },
  { id: 'ayodhya-ayj', name: 'Ayodhya Maharishi Valmiki International Airport', lat: 26.7477, lon: 82.1637 },
  { id: 'amravati-avr', name: 'Amravati Airport', lat: 20.8146, lon: 77.7178 },
  { id: 'sindhudurg-sdw', name: 'Sindhudurg Chipi Airport', lat: 16.0026, lon: 73.5298 },
  { id: 'navi-mumbai-nmi', name: 'Navi Mumbai International Airport', lat: 18.9846, lon: 73.0652 },
  { id: 'shivamogga-rqy', name: 'Shivamogga Rashtrakavi Kuvempu Airport', lat: 13.8580, lon: 75.6189 },
  { id: 'itanagar-hollongi-hgi', name: 'Itanagar Donyi Polo Hollongi Airport', lat: 26.9668, lon: 93.6388 },
  { id: 'bihta-afs', name: 'Bihta Air Force Station', lat: 25.5912, lon: 84.8831 },
  { id: 'yavatmal-in0369', name: 'Yavatmal Sant Gadge Baba Airport', lat: 20.3958, lon: 78.2163 },
  { id: 'noida-dxn', name: 'Noida International Airport (Jewar)', lat: 28.1799, lon: 77.6118 },
  { id: 'ambikapur-aha', name: 'Ambikapur Maa Mahamaya Airport', lat: 22.9875, lon: 83.1961 },
  { id: 'jagdalpur-jgb', name: 'Jagdalpur Airport', lat: 19.0743, lon: 82.0368 },
  { id: 'rewa-va1g', name: 'Rewa Airport', lat: 24.5034, lon: 81.2203 },
  { id: 'naliya-afs', name: 'Naliya Air Force Station', lat: 23.2223, lon: 68.8913 },
  { id: 'gondia-va2c', name: 'Gondia Airport', lat: 21.5268, lon: 80.2903 },
  { id: 'akola-vaak', name: 'Akola Airport', lat: 20.6989, lon: 77.0569 },
  { id: 'daman-vadn', name: 'Daman Airport', lat: 20.4344, lon: 72.8432 },
  { id: 'jalgaon-vajl', name: 'Jalgaon Airport', lat: 20.9627, lon: 75.6275 },
  { id: 'khajuraho-vakj', name: 'Khajuraho Airport', lat: 24.8172, lon: 79.9186 },
  { id: 'keshod-vaks', name: 'Keshod Airport', lat: 21.3171, lon: 70.2704 },
  { id: 'latur-valt', name: 'Latur Murod Kond Airport', lat: 18.4115, lon: 76.4647 },
  { id: 'ratnagiri-varg', name: 'Ratnagiri Airport', lat: 17.0136, lon: 73.3278 },
  { id: 'solapur-vasl', name: 'Solapur Airport', lat: 17.6280, lon: 75.9348 },
  { id: 'charbatia-afs-ve62', name: 'Cuttack Charbatia Air Force Station', lat: 20.5496, lon: 85.8863 },
  { id: 'along-vean', name: 'Along Airport', lat: 28.1753, lon: 94.8020 },
  { id: 'chabua-afs-veca', name: 'Chabua Air Force Station', lat: 27.4622, lon: 95.1177 },
  { id: 'dhanbad-vedb', name: 'Dhanbad Airport', lat: 23.8340, lon: 86.4253 },
  { id: 'durgapur-vedg', name: 'Durgapur Kazi Nazrul Islam Airport', lat: 23.6225, lon: 87.2430 },
  { id: 'kalaikunda-afs-vedx', name: 'Kalaikunda Air Force Station (Kharagpur)', lat: 22.3395, lon: 87.2145 },
  { id: 'hashimara-afs-vehx', name: 'Hashimara Air Force Station', lat: 26.6983, lon: 89.3691 },
  { id: 'jharsuguda-vejh', name: 'Jharsuguda Airport', lat: 21.9135, lon: 84.0504 },
  { id: 'jamshedpur-vejs', name: 'Jamshedpur Sonari Airport', lat: 22.8137, lon: 86.1690 },
  { id: 'kushinagar-veki', name: 'Kushinagar International Airport', lat: 26.7765, lon: 83.8892 },
  { id: 'kailashahar-vekr', name: 'Kailashahar Airport', lat: 24.3087, lon: 92.0077 },
  { id: 'aizawl-velp', name: 'Aizawl Lengpui Airport', lat: 23.8406, lon: 92.6197 },
  { id: 'lilabari-velr', name: 'Lilabari North Lakhimpur Airport', lat: 27.2957, lon: 94.0973 },
  { id: 'muzaffarpur-vemz', name: 'Muzaffarpur Airport', lat: 26.1191, lon: 85.3137 },
  { id: 'panagarh-afs-veph', name: 'Panagarh Air Force Station', lat: 23.4743, lon: 87.4275 },
  { id: 'barrackpore-afs-vepi', name: 'Barrackpore Air Force Station', lat: 22.7810, lon: 88.3592 },
  { id: 'rourkela-verk', name: 'Rourkela Airport', lat: 22.2566, lon: 84.8152 },
  { id: 'utkela-veuk', name: 'Utkela Airport', lat: 20.0978, lon: 83.1833 },
  { id: 'ziro-vezo', name: 'Ziro Airport', lat: 27.5883, lon: 93.8281 },
  { id: 'ambala-afs-viam', name: 'Ambala Air Force Station', lat: 30.3681, lon: 76.8167 },
  { id: 'awantipura-afs-viaw', name: 'Awantipura Air Force Station', lat: 33.8766, lon: 74.9757 },
  { id: 'adampur-viax', name: 'Adampur Airport', lat: 31.4338, lon: 75.7588 },
  { id: 'bakshi-ka-talab-afs-vibl', name: 'Bakshi Ka Talab Air Force Station (Lucknow)', lat: 26.9883, lon: 80.8931 },
  { id: 'kullu-vibr', name: 'Kullu Manali Airport (Bhuntar)', lat: 31.8767, lon: 77.1544 },
  { id: 'bhatinda-afs-vibt', name: 'Bhatinda Air Force Station', lat: 30.2701, lon: 74.7558 },
  { id: 'safdarjung-vidd', name: 'Safdarjung Airport (New Delhi)', lat: 28.5855, lon: 77.2036 },
  { id: 'kangra-vigg', name: 'Kangra Gaggal Airport (Dharamshala)', lat: 32.1649, lon: 76.2630 },
  { id: 'hisar-vihr', name: 'Hisar Maharaja Agrasen International Airport', lat: 29.1861, lon: 75.7414 },
  { id: 'halwara-vihx', name: 'Halwara International Airport', lat: 30.7485, lon: 75.6298 },
  { id: 'jaisalmer-vijr', name: 'Jaisalmer Airport', lat: 26.8887, lon: 70.8650 },
  { id: 'kishangarh-vikg', name: 'Kishangarh Ajmer Airport', lat: 26.5910, lon: 74.8130 },
  { id: 'kota-viko', name: 'Kota Airport', lat: 25.1602, lon: 75.8456 },
  { id: 'ludhiana-vild', name: 'Ludhiana Airport', lat: 30.8547, lon: 75.9526 },
  { id: 'moradabad-vimb', name: 'Moradabad Airport', lat: 28.8175, lon: 78.9219 },
  { id: 'pathankot-vipk', name: 'Pathankot Airport', lat: 32.2336, lon: 75.6344 },
  { id: 'pantnagar-vipt', name: 'Pantnagar Airport', lat: 29.0334, lon: 79.4737 },
  { id: 'phalodi-afs-vipx', name: 'Phalodi Air Force Station', lat: 27.1049, lon: 72.2129 },
  { id: 'sirsa-afs-visa', name: 'Sirsa Air Force Station', lat: 29.5606, lon: 75.0061 },
  { id: 'sarsawa-afs-visp', name: 'Sarsawa Air Force Station', lat: 29.9943, lon: 77.4246 },
  { id: 'shravasti-visv', name: 'Shravasti Airport', lat: 27.4997, lon: 82.0329 },
  { id: 'udhampur-afs-viux', name: 'Udhampur Air Force Station', lat: 32.9022, lon: 75.1557 },
  { id: 'campbell-bay-vo94', name: 'Campbell Bay Airport / INS Baaz', lat: 7.0130, lon: 93.9228 },
  { id: 'arakkonam-voar', name: 'Arakkonam INS Rajali Naval Air Station', lat: 13.0712, lon: 79.6912 },
  { id: 'agatti-voat', name: 'Agatti Airport', lat: 10.8237, lon: 72.1760 },
  { id: 'bellary-vobi', name: 'Bellary Airport', lat: 15.1628, lon: 76.8828 },
  { id: 'bidar-afs-vobr', name: 'Bidar Air Force Station', lat: 17.9081, lon: 77.4871 },
  { id: 'kochi-ins-garuda-vocc', name: 'Kochi INS Garuda Naval Air Station', lat: 9.9461, lon: 76.2719 },
  { id: 'car-nicobar-afb-vocx', name: 'Car Nicobar Air Force Base', lat: 9.1531, lon: 92.8193 },
  { id: 'kalaburagi-vogb', name: 'Kalaburagi Airport', lat: 17.3082, lon: 76.9652 },
  { id: 'begumpet-vohy', name: 'Hyderabad Begumpet Airport', lat: 17.4531, lon: 78.4676 },
  { id: 'kurnool-voku', name: 'Kurnool Orvakal Airport', lat: 15.7163, lon: 78.1692 },
  { id: 'pondicherry-vopc', name: 'Puducherry Airport', lat: 11.9680, lon: 79.8120 },
  { id: 'ramnad-vorm', name: 'Ramnad INS Parundu Naval Air Station', lat: 9.3251, lon: 78.9715 },
  { id: 'sulur-afs-vosx', name: 'Sulur Air Force Station (Coimbatore)', lat: 11.0136, lon: 77.1597 },
  { id: 'thanjavur-afs-votj', name: 'Thanjavur Air Force Station', lat: 10.7238, lon: 79.1095 },
  { id: 'tambaram-afs-votx', name: 'Tambaram Air Force Station (Chennai)', lat: 12.9072, lon: 80.1219 },
  { id: 'vizag-bhogapuram-vovi', name: 'Alluri Sitarama Raju International Airport (Bhogapuram)', lat: 17.9715, lon: 83.5036 },
  { id: 'yelahanka-afs-voyk', name: 'Yelahanka Air Force Station (Bengaluru)', lat: 13.1355, lon: 77.6060 },
]

const INDIA_BOUNDS = {
  south: 6.0,
  north: 38.5,
  west: 66.5,
  east: 98.5,
}

const BORDER_RED_ZONES: RegulatoryZone[] = [
  {
    id: 'intl-boundary-pakistan-kashmir-25km',
    name: 'International Boundary red zone - Pakistan / Kashmir sector',
    country: 'India',
    authority: MAPPLS_AIRSPACE_SOURCE.authority,
    kind: 'red',
    source: MAPPLS_AIRSPACE_SOURCE,
    restriction: 'Approximate 25 km DigitalSky international-boundary no-drone buffer. Central Government permission required.',
    polygon: [
      [23.25, 68.05], [24.15, 69.35], [25.25, 70.55], [26.45, 70.95],
      [27.70, 71.10], [29.15, 72.10], [30.10, 73.45], [31.05, 74.45],
      [32.10, 74.85], [33.40, 74.85], [34.55, 75.35], [35.30, 76.45],
      [34.95, 77.15], [34.05, 76.45], [33.10, 75.80], [31.85, 75.55],
      [30.65, 74.65], [29.75, 73.40], [28.65, 72.60], [27.25, 71.80],
      [25.80, 71.35], [24.65, 70.35], [23.45, 69.25],
    ],
    outerRadiusM: 0,
    maxAltitudeM: 0,
    maxSpeedMs: 0,
    recommendedAltitudeM: 0,
    recommendedSpeedMs: 0,
    requiresPermission: true,
    action: 'rtl',
  },
  {
    id: 'intl-boundary-ladakh-china-25km',
    name: 'International Boundary red zone - Ladakh / China sector',
    country: 'India',
    authority: MAPPLS_AIRSPACE_SOURCE.authority,
    kind: 'red',
    source: MAPPLS_AIRSPACE_SOURCE,
    restriction: 'Approximate 25 km DigitalSky international-boundary no-drone buffer. Central Government permission required.',
    polygon: [
      [34.30, 76.10], [34.85, 77.15], [35.20, 78.40], [34.95, 79.75],
      [34.15, 80.55], [33.45, 79.90], [33.75, 78.35], [33.55, 77.15],
      [33.75, 76.25],
    ],
    outerRadiusM: 0,
    maxAltitudeM: 0,
    maxSpeedMs: 0,
    recommendedAltitudeM: 0,
    recommendedSpeedMs: 0,
    requiresPermission: true,
    action: 'rtl',
  },
  {
    id: 'intl-boundary-himalayan-china-25km',
    name: 'International Boundary red zone - Himalayan / China sector',
    country: 'India',
    authority: MAPPLS_AIRSPACE_SOURCE.authority,
    kind: 'red',
    source: MAPPLS_AIRSPACE_SOURCE,
    restriction: 'Approximate 25 km DigitalSky international-boundary no-drone buffer. Central Government permission required.',
    polygon: [
      [31.20, 78.45], [31.45, 80.20], [30.85, 81.70], [30.25, 83.25],
      [29.85, 84.80], [29.45, 86.40], [28.95, 88.05], [28.55, 89.80],
      [28.05, 91.60], [27.65, 93.35], [27.95, 95.20], [28.35, 96.35],
      [27.60, 97.25], [26.85, 96.45], [26.70, 94.75], [26.95, 92.80],
      [27.35, 90.85], [27.75, 89.05], [28.25, 87.25], [28.75, 85.45],
      [29.20, 83.70], [29.80, 81.95], [30.35, 80.25], [30.65, 78.65],
    ],
    outerRadiusM: 0,
    maxAltitudeM: 0,
    maxSpeedMs: 0,
    recommendedAltitudeM: 0,
    recommendedSpeedMs: 0,
    requiresPermission: true,
    action: 'rtl',
  },
  {
    id: 'intl-boundary-bangladesh-ne-25km',
    name: 'International Boundary red zone - Bangladesh / North East sector',
    country: 'India',
    authority: MAPPLS_AIRSPACE_SOURCE.authority,
    kind: 'red',
    source: MAPPLS_AIRSPACE_SOURCE,
    restriction: 'Approximate 25 km DigitalSky international-boundary no-drone buffer. Central Government permission required.',
    polygon: [
      [21.55, 88.05], [22.20, 89.15], [23.05, 90.10], [24.25, 91.15],
      [25.10, 92.25], [25.55, 93.05], [24.95, 93.55], [23.80, 92.75],
      [22.65, 91.45], [21.75, 90.15], [21.30, 88.85],
    ],
    outerRadiusM: 0,
    maxAltitudeM: 0,
    maxSpeedMs: 0,
    recommendedAltitudeM: 0,
    recommendedSpeedMs: 0,
    requiresPermission: true,
    action: 'rtl',
  },
  {
    id: 'intl-boundary-myanmar-ne-25km',
    name: 'International Boundary red zone - Myanmar / North East sector',
    country: 'India',
    authority: MAPPLS_AIRSPACE_SOURCE.authority,
    kind: 'red',
    source: MAPPLS_AIRSPACE_SOURCE,
    restriction: 'Approximate 25 km DigitalSky international-boundary no-drone buffer. Central Government permission required.',
    polygon: [
      [27.35, 95.00], [26.50, 95.55], [25.35, 95.35], [24.05, 94.90],
      [22.85, 93.85], [21.95, 93.10], [22.25, 92.45], [23.40, 93.20],
      [24.65, 94.15], [25.80, 94.60], [27.00, 94.45],
    ],
    outerRadiusM: 0,
    maxAltitudeM: 0,
    maxSpeedMs: 0,
    recommendedAltitudeM: 0,
    recommendedSpeedMs: 0,
    requiresPermission: true,
    action: 'rtl',
  },
]

const SENSITIVE_RED_ZONES: RegulatoryZone[] = [
  {
    id: 'delhi-central-vip-red',
    name: 'Central Delhi high-security red zone',
    country: 'India',
    authority: DIGITAL_SKY_SOURCE.authority,
    kind: 'red',
    source: PIB_SOURCE,
    restriction: 'High-security government district. No-drone operation unless Central Government permission is granted.',
    center: [28.6143, 77.1999],
    outerRadiusM: 3_000,
    maxAltitudeM: 0,
    maxSpeedMs: 0,
    recommendedAltitudeM: 0,
    recommendedSpeedMs: 0,
    requiresPermission: true,
    action: 'rtl',
  },
  {
    id: 'mumbai-naval-dockyard-red',
    name: 'Mumbai naval dockyard / port red zone',
    country: 'India',
    authority: DIGITAL_SKY_SOURCE.authority,
    kind: 'red',
    source: PIB_SOURCE,
    restriction: 'Sensitive defence and port area. No-drone operation unless Central Government permission is granted.',
    center: [18.9420, 72.8430],
    outerRadiusM: 3_000,
    maxAltitudeM: 0,
    maxSpeedMs: 0,
    recommendedAltitudeM: 0,
    recommendedSpeedMs: 0,
    requiresPermission: true,
    action: 'rtl',
  },
]

function toRad(value: number) {
  return (value * Math.PI) / 180
}

function metersPerDegreeLon(lat: number) {
  return 111_320 * Math.cos(toRad(lat))
}

function distanceMeters(lat1: number, lon1: number, lat2: number, lon2: number) {
  const dLat = (lat2 - lat1) * 111_320
  const dLon = (lon2 - lon1) * metersPerDegreeLon((lat1 + lat2) / 2)
  return Math.sqrt(dLat * dLat + dLon * dLon)
}

function pointInPolygon(lat: number, lon: number, polygon: [number, number][]) {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const yi = polygon[i][0]
    const xi = polygon[i][1]
    const yj = polygon[j][0]
    const xj = polygon[j][1]
    const intersects = ((yi > lat) !== (yj > lat)) &&
      (lon < ((xj - xi) * (lat - yi)) / ((yj - yi) || 1e-12) + xi)
    if (intersects) inside = !inside
  }
  return inside
}

function orientation(a: [number, number], b: [number, number], c: [number, number]) {
  return (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
}

function onSegment(a: [number, number], b: [number, number], c: [number, number]) {
  return b[0] <= Math.max(a[0], c[0]) && b[0] >= Math.min(a[0], c[0]) &&
    b[1] <= Math.max(a[1], c[1]) && b[1] >= Math.min(a[1], c[1])
}

function segmentsIntersect(a: [number, number], b: [number, number], c: [number, number], d: [number, number]) {
  const o1 = orientation(a, b, c)
  const o2 = orientation(a, b, d)
  const o3 = orientation(c, d, a)
  const o4 = orientation(c, d, b)

  if ((o1 > 0) !== (o2 > 0) && (o3 > 0) !== (o4 > 0)) return true
  if (Math.abs(o1) < 1e-12 && onSegment(a, c, b)) return true
  if (Math.abs(o2) < 1e-12 && onSegment(a, d, b)) return true
  if (Math.abs(o3) < 1e-12 && onSegment(c, a, d)) return true
  if (Math.abs(o4) < 1e-12 && onSegment(c, b, d)) return true
  return false
}

function segmentCrossesPolygon(a: [number, number], b: [number, number], polygon: [number, number][]) {
  if (pointInPolygon(a[0], a[1], polygon) || pointInPolygon(b[0], b[1], polygon)) return true

  for (let i = 0; i < polygon.length; i += 1) {
    const next = (i + 1) % polygon.length
    if (segmentsIntersect(a, b, polygon[i], polygon[next])) return true
  }

  return false
}

function zonePolygons(zone: RegulatoryZone) {
  if (zone.polygons) return zone.polygons
  if (zone.polygon) return [zone.polygon]
  return []
}

function polygonCentroid(polygon: [number, number][]): [number, number] | null {
  if (polygon.length === 0) return null
  const total = polygon.reduce(
    (sum, point) => [sum[0] + point[0], sum[1] + point[1]] as [number, number],
    [0, 0] as [number, number],
  )
  return [total[0] / polygon.length, total[1] / polygon.length]
}

function circleRing(centerLat: number, centerLon: number, radiusM: number, steps = 96): [number, number][] {
  const latRadius = radiusM / 111_320
  const lonRadius = radiusM / metersPerDegreeLon(centerLat)
  return Array.from({ length: steps + 1 }, (_, i) => {
    const angle = (i / steps) * Math.PI * 2
    return [
      centerLat + Math.sin(angle) * latRadius,
      centerLon + Math.cos(angle) * lonRadius,
    ] as [number, number]
  })
}

function annulus(centerLat: number, centerLon: number, innerM: number, outerM: number): [number, number][][] {
  const outer = circleRing(centerLat, centerLon, outerM)
  const inner = circleRing(centerLat, centerLon, innerM).reverse()
  return [outer, inner]
}

function styleFor(kind: RegulatoryZoneKind) {
  if (kind === 'red') {
    return { color: '#dc2626', fillColor: '#ef4444', fillOpacity: 0.24 }
  }
  if (kind === 'orange') {
    return { color: '#f97316', fillColor: '#f97316', fillOpacity: 0.2 }
  }
  return { color: '#16a34a', fillColor: '#22c55e', fillOpacity: 0.08 }
}

function buildAirportZones(): RegulatoryZone[] {
  return AIRPORTS.flatMap(airport => {
    const common = {
      country: 'India',
      authority: DIGITAL_SKY_SOURCE.authority,
      center: [airport.lat, airport.lon] as [number, number],
    }

    return [
      {
        ...common,
        id: `${airport.id}-red-0-5`,
        name: `${airport.name} red zone 0-5 km`,
        kind: 'red' as const,
        source: PIB_SOURCE,
        restriction: 'No-drone zone. Operation requires Central Government permission.',
        outerRadiusM: 5_000,
        maxAltitudeM: 0,
        maxSpeedMs: 0,
        recommendedAltitudeM: 0,
        recommendedSpeedMs: 0,
        requiresPermission: true,
        action: 'rtl' as const,
      },
      {
        ...common,
        id: `${airport.id}-yellow-5-8`,
        name: `${airport.name} yellow zone 5-8 km`,
        kind: 'orange' as const,
        source: PIB_SOURCE,
        restriction: 'Yellow zone from ground level. ATC/competent authority permission required.',
        innerRadiusM: 5_000,
        outerRadiusM: 8_000,
        maxAltitudeM: 0,
        maxSpeedMs: 4,
        recommendedAltitudeM: 0,
        recommendedSpeedMs: 0,
        requiresPermission: true,
        action: 'hold' as const,
      },
      {
        ...common,
        id: `${airport.id}-yellow-8-12`,
        name: `${airport.name} yellow zone 8-12 km`,
        kind: 'orange' as const,
        source: PIB_SOURCE,
        restriction: 'Yellow zone above 200 ft / 60 m AGL. Stay below 60 m unless permission is granted.',
        innerRadiusM: 8_000,
        outerRadiusM: 12_000,
        maxAltitudeM: 60,
        maxSpeedMs: 8,
        recommendedAltitudeM: 50,
        recommendedSpeedMs: 5,
        requiresPermission: true,
        action: 'reduce' as const,
      },
    ]
  })
}

export const regulatoryZones: RegulatoryZone[] = [
  ...BORDER_RED_ZONES,
  ...SENSITIVE_RED_ZONES,
  ...buildAirportZones(),
]

export function getRegulatoryZoneLoadState() {
  return {
    offline: true,
    checkedOn: OFFLINE_SNAPSHOT_CHECKED_ON,
    count: regulatoryZones.length,
  }
}

export function isInsideIndia(lat: number, lon: number) {
  return lat >= INDIA_BOUNDS.south && lat <= INDIA_BOUNDS.north &&
    lon >= INDIA_BOUNDS.west && lon <= INDIA_BOUNDS.east
}

function isInsideZone(zone: RegulatoryZone, lat: number, lon: number) {
  const polygons = zonePolygons(zone)
  if (polygons.length > 0) return polygons.some(polygon => pointInPolygon(lat, lon, polygon))
  if (!zone.center) return false
  const d = distanceMeters(zone.center[0], zone.center[1], lat, lon)
  if (d > zone.outerRadiusM) return false
  if (zone.innerRadiusM && d < zone.innerRadiusM) return false
  return true
}

function zonePriority(kind: RegulatoryZoneKind) {
  if (kind === 'red') return 3
  if (kind === 'orange') return 2
  return 1
}

function toRule(zone: RegulatoryZone): RegulatoryRule {
  return {
    id: zone.id,
    name: zone.name,
    kind: zone.kind,
    action: zone.action,
    authority: zone.authority,
    source: zone.source,
    restriction: zone.restriction,
    maxAltitudeM: zone.maxAltitudeM,
    maxSpeedMs: zone.maxSpeedMs,
    recommendedAltitudeM: zone.recommendedAltitudeM,
    recommendedSpeedMs: zone.recommendedSpeedMs,
    requiresPermission: zone.requiresPermission,
  }
}

export function getRegulatoryRule(lat: number, lon: number, altitudeM = 0): RegulatoryRule | null {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null

  const matching = regulatoryZones
    .filter(zone => isInsideZone(zone, lat, lon))
    .sort((a, b) => zonePriority(b.kind) - zonePriority(a.kind))

  const zone = matching[0]
  if (zone) return toRule(zone)

  if (isInsideIndia(lat, lon)) {
    const maxAltitudeM = 120
    return {
      id: 'india-green-open-airspace',
      name: 'India green zone',
      kind: altitudeM > maxAltitudeM ? 'orange' : 'green',
      action: altitudeM > maxAltitudeM ? 'reduce' : 'continue',
      authority: DIGITAL_SKY_SOURCE.authority,
      source: PIB_SOURCE,
      restriction: 'Green zone up to 400 ft / 120 m AGL outside red/yellow zones.',
      maxAltitudeM,
      maxSpeedMs: 12,
      recommendedAltitudeM: 100,
      recommendedSpeedMs: 8,
      requiresPermission: false,
    }
  }

  return null
}

export function findRegulatoryZone(lat: number, lon: number, altitudeM = 0) {
  return getRegulatoryRule(lat, lon, altitudeM)
}

export function routeSegmentCrossesRestrictedZone(
  prev: { lat: number; lng: number },
  next: { lat: number; lng: number },
): string | null {
  const segmentStart: [number, number] = [prev.lat, prev.lng]
  const segmentEnd: [number, number] = [next.lat, next.lng]

  for (const zone of regulatoryZones) {
    if (zone.kind === 'green') continue

    const polygons = zonePolygons(zone)
    if (polygons.some(polygon => segmentCrossesPolygon(segmentStart, segmentEnd, polygon))) return zone.name

    if (zone.center) {
      const [zLat, zLon] = zone.center
      const radius = zone.outerRadiusM || 12_000
      const dist = segmentMinDistanceMeters(prev.lat, prev.lng, next.lat, next.lng, zLat, zLon)
      if (dist <= radius) return zone.name
    }
  }

  return null
}

export function drawnPolygonContainsRestrictedZone(points: { lat: number; lng: number }[]): string | null {
  if (points.length < 3) return null
  const polygon = points.map(point => [point.lat, point.lng] as [number, number])

  for (const zone of regulatoryZones) {
    if (zone.kind === 'green') continue

    if (zone.center && pointInPolygon(zone.center[0], zone.center[1], polygon)) return zone.name

    for (const zonePolygon of zonePolygons(zone)) {
      const centroid = polygonCentroid(zonePolygon)
      if (centroid && pointInPolygon(centroid[0], centroid[1], polygon)) return zone.name
      if (zonePolygon.some(point => pointInPolygon(point[0], point[1], polygon))) return zone.name
    }
  }

  return null
}

function segmentMinDistanceMeters(
  aLat: number,
  aLng: number,
  bLat: number,
  bLng: number,
  pLat: number,
  pLng: number,
) {
  const refLat = (aLat + bLat + pLat) / 3
  const scaleLat = 111_320
  const scaleLon = 111_320 * Math.cos(toRad(refLat))
  const ax = aLng * scaleLon
  const ay = aLat * scaleLat
  const bx = bLng * scaleLon
  const by = bLat * scaleLat
  const px = pLng * scaleLon
  const py = pLat * scaleLat
  const dx = bx - ax
  const dy = by - ay
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) return Math.hypot(px - ax, py - ay)
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lenSq))
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}

export function buildRegulatoryZoneLayers(): RegulatoryZoneLayer[] {
  return regulatoryZones.flatMap(zone => {
    const style = styleFor(zone.kind)
    const polygons = zonePolygons(zone)

    if (polygons.length > 0) {
      return polygons.map((positions, index) => ({
        ...toRule(zone),
        id: index === 0 ? zone.id : `${zone.id}-${index}`,
        positions,
        ...style,
      }))
    }

    if (!zone.center) return []

    const positions = zone.innerRadiusM
      ? annulus(zone.center[0], zone.center[1], zone.innerRadiusM, zone.outerRadiusM)
      : circleRing(zone.center[0], zone.center[1], zone.outerRadiusM)

    return [{ ...toRule(zone), positions, ...style }]
  })
}

export const regulatorySources = [DIGITAL_SKY_SOURCE, PIB_SOURCE, MAPPLS_AIRSPACE_SOURCE]
