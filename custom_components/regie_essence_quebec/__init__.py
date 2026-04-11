    if not hass.services.has_service(DOMAIN, "find_closest_stations"):
        async def find_closest_stations(call: ServiceCall) -> dict:
            raw_lat = call.data.get("latitude")
            raw_lon = call.data.get("longitude")
            limit = int(call.data.get("limit", 3))
            radius = float(call.data.get("radius", 10.0))
            gas_type = call.data.get("gas_type", "Régulier").strip().lower()

            if raw_lat is None or raw_lon is None or raw_lat == "" or raw_lon == "" or raw_lat == "None" or raw_lon == "None":
                raise ValueError("Could not read GPS coordinates.")

            try:
                lat = float(raw_lat)
                lon = float(raw_lon)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid coordinates provided: lat={raw_lat}, lon={raw_lon}")

            if lat == 0 or lon == 0:
                raise ValueError("Latitude and longitude cannot be zero.")

            client = coordinator._client
            stations = await client.async_get_all_stations()
            valid_stations = []

            # Account for different spelling variations in the government data
            target_types = [gas_type]
            if gas_type in ["régulier", "regulier", "ordinaire"]:
                target_types = ["régulier", "regulier", "ordinaire"]
            elif gas_type in ["diesel", "diésel"]:
                target_types = ["diesel", "diésel"]

            for s in stations:
                s_lat = s.get("latitude", 0)
                s_lon = s.get("longitude", 0)
                if s_lat and s_lon:
                    R = 6371.0 
                    dlat = math.radians(s_lat - lat)
                    dlon = math.radians(s_lon - lon)
                    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(s_lat)) * math.sin(dlon / 2)**2
                    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                    dist = round(R * c, 2)
                    
                    if dist <= radius:
                        s["distance_km"] = dist
                        
                        for price_item in s.get("Prices", []):
                            actual_type = price_item.get("GasType", "").strip().lower()
                            if actual_type in target_types:
                                raw_price = str(price_item.get("Price", ""))
                                match = re.search(r"([\d\.]+)", raw_price)
                                if match:
                                    s["target_price"] = float(match.group(1))
                                    valid_stations.append(s)
                                    break

            # Create the two distinct lists
            by_distance = sorted(valid_stations, key=lambda x: x.get("distance_km", 99999))
            by_price = sorted(valid_stations, key=lambda x: (x.get("target_price", 999.9), x.get("distance_km", 99999)))

            return {
                "closest": by_distance[:limit],
                "cheapest": by_price[:limit]
            }

        hass.services.async_register(
            DOMAIN, "find_closest_stations", find_closest_stations,
            supports_response=SupportsResponse.ONLY
        )
