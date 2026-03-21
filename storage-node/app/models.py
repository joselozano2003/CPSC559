from .extensions import db


class Chunk(db.Model):
    __tablename__ = "chunks"

    id = db.Column(db.Integer, primary_key=True)
    chunk_id = db.Column(db.String(64), unique=True, nullable=False)
    minio_object_key = db.Column(db.String(256), nullable=False)
    file_id = db.Column(db.String(64), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=True)
    confirmed = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            "chunk_id": self.chunk_id,
            "minio_object_key": self.minio_object_key,
            "file_id": self.file_id,
            "size_bytes": self.size_bytes,
            "confirmed": self.confirmed,
        }