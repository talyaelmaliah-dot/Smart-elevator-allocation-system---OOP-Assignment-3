from random import Random

from .contracts import GeneratedTraffic, TrafficProfile
from .domain import Building, PassengerRequest


class RequestGenerator:
    def generate(
        self, building: Building, spec: GeneratedTraffic
    ) -> tuple[PassengerRequest, ...]:
        profile = TrafficProfile(spec.profile)
        for field, minimum in (
            ("seed", 0), ("request_count", 0), ("duration_ms", 1)
        ):
            value = getattr(spec, field)
            if type(value) is not int or value < minimum:
                raise ValueError(f"{field} must be an integer >= {minimum}")

        floor_count = len(building.floors)
        if floor_count < 2:
            raise ValueError("generation requires at least two floors")

        rng = Random(spec.seed)
        lobby = building.lobby_floor
        profiles = (
            TrafficProfile.RANDOM,
            TrafficProfile.MORNING_RUSH,
            TrafficProfile.EVENING_RUSH,
        )
        requests = []
        for number in range(1, spec.request_count + 1):
            timestamp = rng.randrange(spec.duration_ms)
            direction = rng.choice(profiles) if profile is TrafficProfile.MIXED else profile

            if direction is TrafficProfile.RANDOM:
                origin = rng.randrange(floor_count)
                destination = rng.randrange(floor_count - 1)
                destination += destination >= origin
            else:
                other = rng.randrange(floor_count - 1)
                other += other >= lobby
                if direction is TrafficProfile.MORNING_RUSH:
                    origin, destination = lobby, other
                else:
                    origin, destination = other, lobby

            requests.append(PassengerRequest(f"R{number}", timestamp, origin, destination))

        return tuple(sorted(requests, key=lambda request: (request.requested_at_ms, request.id)))
