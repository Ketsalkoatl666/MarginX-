from collections import defaultdict


class EventBus:
    """Tiny publish/subscribe hub. UI and logs listen; they never touch hardware."""

    def __init__(self):
        self._subs = defaultdict(list)

    def subscribe(self, topic, fn):
        self._subs[topic].append(fn)

    def publish(self, topic, **data):
        for fn in list(self._subs[topic]) + list(self._subs["*"]):
            fn(topic, data)
