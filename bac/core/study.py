"""Server-owned curriculum choices and conversation-bound publication access."""

import json
from fastapi import HTTPException

TRACKS = {
    "experimental_sciences": (
        "علوم تجريبية",
        ["science", "scientific", "علوم", "علوم تجريبية"],
    ),
    "mathematics": ("رياضيات", ["math", "maths", "mathematics", "رياضيات"]),
    "technical_mathematics": ("تقني رياضي", ["technical mathematics", "تقني رياضي"]),
    "management_economics": ("تسيير واقتصاد", ["تسيير واقتصاد", "تسيير و اقتصاد"]),
    "literature_philosophy": ("آداب وفلسفة", ["آداب وفلسفة", "آداب و فلسفة"]),
    "foreign_languages": ("لغات أجنبية", ["لغات أجنبية"]),
}
SUBJECTS = {
    "physics": (
        "العلوم الفيزيائية",
        ["physics", "physique", "فيزياء", "الفيزياء", "العلوم الفيزيائية"],
    ),
    "mathematics": (
        "الرياضيات",
        ["math", "maths", "mathematics", "رياضيات", "الرياضيات"],
    ),
    "natural_sciences": (
        "علوم الطبيعة والحياة",
        ["علوم الطبيعة والحياة", "العلوم الطبيعية"],
    ),
    "arabic": ("اللغة العربية", ["اللغة العربية", "عربية"]),
    "french": ("اللغة الفرنسية", ["اللغة الفرنسية", "فرنسية", "french"]),
    "english": ("اللغة الإنجليزية", ["اللغة الإنجليزية", "انجليزية", "english"]),
    "history_geography": (
        "التاريخ والجغرافيا",
        ["التاريخ والجغرافيا", "تاريخ وجغرافيا"],
    ),
    "islamic_studies": ("العلوم الإسلامية", ["العلوم الإسلامية", "التربية الإسلامية"]),
    "philosophy": ("الفلسفة", ["الفلسفة", "فلسفة"]),
    "amazigh": ("اللغة الأمازيغية", ["اللغة الأمازيغية"]),
    "spanish": ("اللغة الإسبانية", ["اللغة الإسبانية"]),
    "german": ("اللغة الألمانية", ["اللغة الألمانية"]),
    "italian": ("اللغة الإيطالية", ["اللغة الإيطالية"]),
    "economics": ("الاقتصاد والمناجمنت", ["الاقتصاد والمناجمنت", "التسيير والاقتصاد"]),
    "accounting": ("التسيير المحاسبي والمالي", ["التسيير المحاسبي والمالي", "محاسبة"]),
    "law": ("القانون", ["القانون"]),
    "electrical_engineering": ("الهندسة الكهربائية", ["الهندسة الكهربائية"]),
    "mechanical_engineering": ("الهندسة الميكانيكية", ["الهندسة الميكانيكية"]),
    "civil_engineering": ("الهندسة المدنية", ["الهندسة المدنية"]),
    "process_engineering": ("هندسة الطرائق", ["هندسة الطرائق"]),
}
COMMON = [
    "arabic",
    "french",
    "english",
    "mathematics",
    "history_geography",
    "islamic_studies",
    "philosophy",
    "amazigh",
]
TRACK_SUBJECTS = {
    "experimental_sciences": COMMON + ["physics", "natural_sciences"],
    "mathematics": COMMON + ["physics", "natural_sciences"],
    "technical_mathematics": COMMON
    + [
        "physics",
        "electrical_engineering",
        "mechanical_engineering",
        "civil_engineering",
        "process_engineering",
    ],
    "management_economics": COMMON + ["economics", "accounting", "law"],
    "literature_philosophy": COMMON,
    "foreign_languages": COMMON + ["spanish", "german", "italian"],
}
CONTENT_TYPES = {
    "textbook": ("كتاب مدرسي", "book"),
    "school_tests": ("فروض واختبارات", "exam"),
    "exercises": ("تمارين", "exercise_collection"),
    "bac_exams": ("امتحانات البكالوريا", "exam"),
}


def aliases(entries, code):
    return list(dict.fromkeys([code, entries[code][0], *entries[code][1]]))


def resolve(entries, value):
    if not isinstance(value, str):
        return None
    value = value.strip().casefold()
    return next(
        (
            code
            for code in entries
            if value in [x.casefold() for x in aliases(entries, code)]
        ),
        None,
    )


def validate_pair(track, subject):
    t = resolve(TRACKS, track)
    q = resolve(SUBJECTS, subject)
    if not t or not q or q not in TRACK_SUBJECTS[t]:
        raise ValueError("Choose a predefined track and a subject belonging to it")
    return t, q


def normalize_source_tracks(tracks, legacy_track, subject):
    values = tracks if tracks is not None else [legacy_track]
    if not values:
        raise ValueError("Select at least one predefined target track")
    resolved = list(dict.fromkeys(validate_pair(t, subject)[0] for t in values))
    return resolved, validate_pair(resolved[0], subject)[1]


def document_tracks(doc):
    meta = doc.get("metadata", {})
    if isinstance(meta, str):
        meta = json.loads(meta)
    values = (
        meta.get("tracks") or doc.get("tracks") or [doc.get("track", meta.get("track"))]
    )
    return list(dict.fromkeys(t for v in values if (t := resolve(TRACKS, v))))


def track_sql(prefix, values):
    # Old publications remain single-track without rewriting their frozen snapshots.
    members = (
        "CASE WHEN json_type("
        + prefix
        + "metadata,'$.tracks')='array' AND json_array_length("
        + prefix
        + "metadata,'$.tracks')>0 THEN json_extract("
        + prefix
        + "metadata,'$.tracks') ELSE json_array("
        + prefix
        + "track) END"
    )
    return (
        "EXISTS(SELECT 1 FROM json_each("
        + members
        + ") AS source_track WHERE lower(trim(source_track.value)) IN ("
        + ",".join("?" for _ in values)
        + "))"
    )


def catalogue():
    return {
        "tracks": [
            {
                "id": t,
                "label": v[0],
                "aliases": aliases(TRACKS, t),
                "subjects": [
                    {"id": s, "label": SUBJECTS[s][0], "aliases": aliases(SUBJECTS, s)}
                    for s in TRACK_SUBJECTS[t]
                ],
            }
            for t, v in TRACKS.items()
        ],
        "content_types": [
            {"id": t, "label": v[0], "kind": v[1]} for t, v in CONTENT_TYPES.items()
        ],
    }


def select_track(db, user, value):
    if user["role"] != "student":
        raise HTTPException(403, "Student account required")
    if value not in TRACKS:
        raise HTTPException(422, "Choose a predefined track")
    with db.tx() as c:
        row = c.execute(
            "SELECT study_track FROM users WHERE id=?", (user["id"],)
        ).fetchone()
        if row["study_track"] is not None and row["study_track"] != value:
            raise HTTPException(409, "The selected study track cannot be changed")
        c.execute(
            "UPDATE users SET study_track=?,study_track_selected_at=coalesce(study_track_selected_at,strftime('%s','now')) WHERE id=?",
            (value, user["id"]),
        )
    return db.one("SELECT * FROM users WHERE id=?", (user["id"],))


class StudyScope:
    def __init__(self, db, user, chat):
        self.db = db
        self.track = None
        self.subject = None
        if user["role"] != "student":
            return
        u = db.one("SELECT study_track FROM users WHERE id=?", (user["id"],))
        c = db.one(
            "SELECT study_subject FROM conversations WHERE id=? AND user_id=?",
            (chat, user["id"]),
        )
        if not u or not u["study_track"] or not c or not c["study_subject"]:
            raise HTTPException(
                409, "Choose your study track and a conversation subject first"
            )
        self.track, self.subject = validate_pair(u["study_track"], c["study_subject"])

    def sql(self, query, params, prefix="d."):
        if self.track is None:
            return query, params
        tracks = aliases(TRACKS, self.track)
        query += " AND " + track_sql(prefix, tracks)
        params.extend(x.casefold() for x in tracks)
        values = aliases(SUBJECTS, self.subject)
        query += (
            " AND lower(trim("
            + prefix
            + "subject)) IN ("
            + ",".join("?" for _ in values)
            + ")"
        )
        params.extend(x.casefold() for x in values)
        return query, params

    def check(self, document_id):
        if self.track is None:
            return
        d = self.db.one(
            "SELECT track,subject,metadata FROM documents WHERE id=?", (document_id,)
        )
        if (
            not d
            or self.track not in document_tracks(d)
            or resolve(SUBJECTS, d["subject"]) != self.subject
        ):
            raise HTTPException(404, "Published source not found in this conversation")


def content_type(doc):
    meta = doc.get("metadata", {})
    if isinstance(meta, str):
        meta = json.loads(meta)
    return meta.get("content_type") or {
        "book": "textbook",
        "reference": "textbook",
        "exam": "school_tests",
        "exercise_collection": "exercises",
    }.get(doc["kind"], "textbook")
