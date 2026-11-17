from destiny_brain.costs import Usage
from destiny_brain.providers.base import ProviderResult


def make_result(text="Hello there.", model="claude-haiku-5-5", stop_reason="end_turn",
                tool_calls=None, usage=Usage(100, 20)):
    content = [{"type": "text", "text": text}]
    if tool_calls:
        content = [{"type": "tool_use", "id": "tu_1", "name": n, "input": i} for n, i in tool_calls]
    return ProviderResult(text=text, content=content, tool_calls=list(tool_calls or []),
                          stop_reason=stop_reason, usage=usage, model=model)


class FakeProvider:
    """Scripted results (or exceptions); records each call's kwargs (messages are snapshotted)."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def complete(self, *, model, system, messages, tools, effort, max_tokens=1024, timeout=None):
        self.calls.append(dict(model=model, system=system, messages=[dict(m) for m in messages],
                               tools=tools, effort=effort, max_tokens=max_tokens, timeout=timeout))
        r = self.results.pop(0) if self.results else make_result(model=model)
        if isinstance(r, Exception):
            raise r
        return r


class FakeHA:
    def __init__(self, weather="Home weather now: sunny, 69°F, humidity 26%."):
        self.weather = weather
        self.notifications = []

    def weather_line(self, entity_id):
        return self.weather

    def notify(self, service, title, message):
        self.notifications.append((service, title, message))
        return True
