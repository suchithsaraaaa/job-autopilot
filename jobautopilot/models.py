from dataclasses import dataclass, field


@dataclass
class Job:
    id: str                 # globally unique: "<ats>:<company>:<native id>"
    ats: str                # greenhouse | lever | ashby
    company: str
    title: str
    location: str
    url: str                # public posting page
    apply_url: str
    description: str        # plain text
    posted_at: str | None = None   # ISO-8601 if the board provides it
    department: str = ""
    remote: bool = False
    extra: dict = field(default_factory=dict)
