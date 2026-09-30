"""Classification engine for Internships, Startups, and Student Eligibility."""
import re
from .models import Job

_TITLE_INTERN = re.compile(
    r"\b(interns?|internships?|co-?ops?|trainees?|apprentices?(?:ships?)?|working students?"
    r"|student (?:engineers?|developers?|researchers?|workers?)|fellows?(?:ships?)?)\b",
    re.I,
)

_DESC_INTERN_POSITIVE = re.compile(
    r"\b(this (?:internship|intern position|intern role)|as an? intern|intern responsibilities"
    r"|duration:\s*\d+\s*(?:weeks?|months?)|internship program"
    r"|(?:summer|winter|spring|fall)\s*202\d\s*intern"
    r"|currently enrolled (?:in|as)|pursuing (?:a |a bachelor'?s?|master'?s?|b\.?tech|degree))\b",
    re.I,
)

_PAST_INTERNSHIP_EXP = re.compile(
    r"\b(?:prior|previous|past|\d+\+?\s*(?:years?|months?)\s*of)\s*(?:internship|intern)\s*experience\b"
    r"|\binternship experience (?:is |would be )?(?:preferred|required|a plus)\b",
    re.I,
)

_GRAD_YEAR_EXPLICIT = re.compile(
    r"\b(?:graduat(?:ing|ion)|class of|batch(?: of)?|passout|expected completion)[^\n.]{0,35}\b(202[3-9])\b",
    re.I,
)
_GRAD_YEAR_STANDALONE = re.compile(r"\b(202[4-9])\s*(?:grads?|graduates?|batch)\b", re.I)

_STUDENT_STATUS = re.compile(
    r"\b(currently enrolled|pursuing (?:bachelor'?s?|master'?s?|b\.?tech|b\.?e\.?|degree)"
    r"|pre-final year|penultimate year|undergraduate student|university student)\b",
    re.I,
)


def is_internship(job: Job) -> bool:
    """Determine whether a job is an internship without false positives from experience mentions."""
    title = job.title or ""
    if _TITLE_INTERN.search(title):
        return True

    dept = job.department or ""
    if _TITLE_INTERN.search(dept):
        return True

    text = job.description or ""
    # Strip past internship experience references before checking description
    stripped = _PAST_INTERNSHIP_EXP.sub("", text)
    if _DESC_INTERN_POSITIVE.search(stripped):
        # Only classify from description if title does not explicitly say Senior/Lead/Staff
        if not re.search(r"\b(senior|sr\.?|lead|staff|principal|director|manager)\b", title, re.I):
            return True

    return False


def is_startup(job: Job, startup_slugs: set[str] | None = None) -> bool:
    """Determine whether a job is from a startup."""
    if job.source == "startup":
        return True
    if "startup" in job.categories:
        return True
    if startup_slugs:
        # Check by company name or native slug in job id
        comp_lower = job.company.lower().strip()
        job_id_lower = job.id.lower()
        for slug in startup_slugs:
            s = slug.lower().strip()
            if s == comp_lower or f":{s}:" in job_id_lower:
                return True
    return False


def is_full_time(job: Job) -> bool:
    """Determine whether a job represents a full-time position."""
    if "full_time" in job.categories:
        return True
    return not is_internship(job)


def detect_student_eligibility(job: Job, target_grad_year: int = 2027) -> str:
    """Determine whether a 2027 graduate is eligible.

    Returns:
      - '2027 students eligible'
      - 'ineligible (requires earlier graduation)'
      - 'unknown'
    """
    text = f"{job.title}\n{job.description}"

    # Extract all mentioned graduation years
    years = [int(y) for y in _GRAD_YEAR_EXPLICIT.findall(text)]
    years += [int(y) for y in _GRAD_YEAR_STANDALONE.findall(text)]

    if years:
        if target_grad_year in years or (target_grad_year - 1 in years and target_grad_year + 1 in years):
            return f"{target_grad_year} students eligible"
        # If explicitly requires earlier graduation (e.g., 2024 or 2025 only)
        if all(y < target_grad_year for y in years):
            return "ineligible (requires earlier graduation)"
        if any(y >= target_grad_year for y in years):
            return f"{target_grad_year} students eligible"

    if _STUDENT_STATUS.search(text):
        return f"{target_grad_year} students eligible"

    return "unknown"


def classify_job(job: Job, is_startup_source: bool = False, target_grad_year: int = 2027) -> Job:
    """Enrich job with employment_type, categories, and eligibility."""
    intern = is_internship(job)
    cats = []

    if is_startup_source or job.source == "startup" or "startup" in job.categories:
        cats.append("startup")
        job.source = "startup"

    if intern:
        job.employment_type = "internship"
        cats.append("internship")
    else:
        job.employment_type = "full_time"
        cats.append("full_time")

    job.categories = list(dict.fromkeys(cats))  # unique preserving order
    job.eligibility = detect_student_eligibility(job, target_grad_year)
    return job
