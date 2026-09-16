from database.connection import get_connection


class DoctorDAO:
    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM doctors ORDER BY doctor_name"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(doctor_id: int) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM doctors WHERE id = ?", (doctor_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def name_exists(name: str, exclude_id: int | None = None) -> bool:
        conn = get_connection()
        try:
            if exclude_id is not None:
                row = conn.execute(
                    "SELECT 1 FROM doctors WHERE doctor_name = ? AND id != ?",
                    (name, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM doctors WHERE doctor_name = ?",
                    (name,),
                ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def search(name: str) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM doctors WHERE doctor_name LIKE ? ORDER BY doctor_name",
                (f"%{name}%",),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def insert(
        doctor_name: str,
        city: str = "",
        specialty: str = "",
        phone_no: str = "",
    ) -> int:
        conn = get_connection()
        try:
            cursor = conn.execute(
                """INSERT INTO doctors (
                    doctor_name, city, specialty, phone_no
                ) VALUES (?, ?, ?, ?)""",
                (doctor_name, city, specialty, phone_no),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def update(
        doctor_id: int,
        doctor_name: str,
        city: str = "",
        specialty: str = "",
        phone_no: str = "",
    ) -> None:
        conn = get_connection()
        try:
            conn.execute(
                """UPDATE doctors SET
                    doctor_name = ?,
                    city = ?,
                    specialty = ?,
                    phone_no = ?
                WHERE id = ?""",
                (doctor_name, city, specialty, phone_no, doctor_id),
            )
            conn.commit()
        finally:
            conn.close()
