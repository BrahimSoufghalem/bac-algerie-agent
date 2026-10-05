ALTER TABLE users ADD COLUMN study_track TEXT CHECK(study_track IS NULL OR study_track IN ('experimental_sciences','mathematics','technical_mathematics','management_economics','literature_philosophy','foreign_languages'));
ALTER TABLE users ADD COLUMN study_track_selected_at REAL;
ALTER TABLE conversations ADD COLUMN study_subject TEXT CHECK(study_subject IS NULL OR study_subject IN ('physics','mathematics','natural_sciences','arabic','french','english','history_geography','islamic_studies','philosophy','amazigh','spanish','german','italian','economics','accounting','law','electrical_engineering','mechanical_engineering','civil_engineering','process_engineering'));
CREATE TRIGGER study_track_immutable BEFORE UPDATE OF study_track ON users
WHEN OLD.study_track IS NOT NULL AND NEW.study_track IS NOT OLD.study_track
BEGIN SELECT RAISE(ABORT,'study_track_immutable'); END;
CREATE TRIGGER conversation_subject_immutable BEFORE UPDATE OF study_subject ON conversations
WHEN NEW.study_subject IS NOT OLD.study_subject AND EXISTS(SELECT 1 FROM messages WHERE conversation_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'conversation_subject_immutable'); END;