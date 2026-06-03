from scipy.optimize import least_squares


class TrilaterationController:
    def __init__(
        self,
        receivers: dict,
        path_loss_exponent: float,
        min_distance_meters: float = 0.0,
    ):
        if not receivers:
            raise ValueError("Receivers must be provided")
        if path_loss_exponent is None:
            raise ValueError("Path loss exponent must be provided")
        if min_distance_meters < 0:
            raise ValueError("Minimum distance must not be negative")

        for receiver_id, receiver in receivers.items():
            if "position" not in receiver:
                raise ValueError(f"Missing position for receiver {receiver_id}")
            if "measured_power" not in receiver:
                raise ValueError(f"Missing measured_power for receiver {receiver_id}")

        self.receivers = receivers
        self.path_loss_exponent = path_loss_exponent
        self.min_distance_meters = min_distance_meters

    def set_measured_power(self, receiver_id: int, measured_power: float):
        if receiver_id not in self.receivers:
            raise ValueError(f"Receiver {receiver_id} is not configured")
        if measured_power is None:
            raise ValueError(f"Measured power for receiver {receiver_id} is required")

        self.receivers[receiver_id]["measured_power"] = measured_power

    def get_position(self, rssi_by_receiver: dict) -> tuple:
        if not rssi_by_receiver:
            raise ValueError("RSSI values must be provided")
        if len(rssi_by_receiver) < 3:
            raise ValueError("At least 3 receiver RSSI values are required")

        base_stations = []
        for receiver_id, rssi in rssi_by_receiver.items():
            if receiver_id not in self.receivers:
                raise ValueError(f"Receiver {receiver_id} is not configured")
            if rssi is None:
                raise ValueError(f"RSSI for receiver {receiver_id} is required")

            receiver = self.receivers[receiver_id]
            base_stations.append(
                {
                    "position": receiver["position"],
                    "distance": self.get_distance(rssi, receiver_id),
                }
            )

        return self.multilaterate(base_stations)

    def multilaterate(self, base_stations: list) -> tuple:
        if len(base_stations) < 3:
            raise ValueError("At least 3 base stations are required")

        positions = [base_station["position"] for base_station in base_stations]
        initial_x = sum(position[0] for position in positions) / len(positions)
        initial_y = sum(position[1] for position in positions) / len(positions)

        def residuals(guess):
            x, y = guess
            errors = []

            for base_station in base_stations:
                receiver_x, receiver_y = base_station["position"]
                measured_distance = base_station["distance"]
                estimated_distance = (
                    (x - receiver_x) ** 2 + (y - receiver_y) ** 2
                ) ** 0.5
                weight_floor = max(self.min_distance_meters, 0.1)
                errors.append(
                    (estimated_distance - measured_distance)
                    / max(measured_distance, weight_floor)
                )

            return errors

        result = least_squares(residuals, (initial_x, initial_y), bounds=([0, 0], [float("inf"), float("inf")]), loss="soft_l1")
        return result.x[0], result.x[1]

    def get_distance(self, rssi: float, receiver_id: int) -> float:
        if receiver_id not in self.receivers:
            raise ValueError(f"Receiver {receiver_id} is not configured")
        if rssi is None:
            raise ValueError(f"RSSI for receiver {receiver_id} is required")

        measured_power = self.receivers[receiver_id]["measured_power"]
        if measured_power is None:
            raise ValueError(
                f"Measured power for receiver {receiver_id} is not available yet"
            )

        distance = 10 ** ((measured_power - rssi) / (10 * self.path_loss_exponent))
        return max(distance, self.min_distance_meters)

    def __str__(self):
        return f"TrilaterationController(receivers={self.receivers})"

    def __repr__(self):
        return self.__str__()
