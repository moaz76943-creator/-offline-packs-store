import os
import hashlib
import tempfile
import shutil

class StorageError(Exception):
    pass

class PackStorage:
    def __init__(self, output_path: str):
        self.output_path = output_path
        self.temp_path = None

    def stage_pack(self, data: bytes):
        """Writes the pack data to a temporary file."""
        fd, self.temp_path = tempfile.mkstemp(prefix="media_pack_", suffix=".vp")
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
        except Exception as e:
            self.rollback()
            raise StorageError(f"Failed to write stage pack: {e}")

    def commit(self) -> dict:
        """Atomically moves the temp file to the final output path and returns metadata."""
        if not self.temp_path or not os.path.exists(self.temp_path):
            raise StorageError("No staged pack to commit")

        try:
            # Calculate SHA-256 and size
            with open(self.temp_path, 'rb') as f:
                data = f.read()

            sha256 = hashlib.sha256(data).hexdigest()
            size = len(data)

            # Atomic rename (replace if exists)
            os.replace(self.temp_path, self.output_path)

            return {
                "sha256": sha256,
                "size": size,
                "path": self.output_path
            }
        except Exception as e:
            self.rollback()
            raise StorageError(f"Failed to commit pack: {e}")

    def rollback(self):
        """Cleans up the temporary file on failure."""
        if self.temp_path and os.path.exists(self.temp_path):
            try:
                os.remove(self.temp_path)
            except OSError:
                pass
        self.temp_path = None
