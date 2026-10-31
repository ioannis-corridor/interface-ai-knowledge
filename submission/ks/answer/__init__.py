"""Answer composition. `Composer.compose(query, snapshot_id, ref_date)` returns a Draft built only from facts
and quoted sentences; the KnowledgeSystem turns the Draft into the harness's Answer."""
from .composer import Composer
from .draft import Draft

__all__ = ["Composer", "Draft"]
