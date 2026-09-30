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
    employment_type: str = "full_time"   # full_time | internship | contract
    categories: list[str] = field(default_factory=list) # e.g. ["internship", "startup"]
    source: str = ""        # company | startup
    eligibility: str = "unknown" # e.g. "2027 students eligible", "unknown", "ineligible"
    extra: dict = field(default_factory=dict)

    @property
    def category(self) -> str:
        return ", ".join(self.categories) if self.categories else self.employment_type

