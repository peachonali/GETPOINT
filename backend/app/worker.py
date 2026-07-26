"""worker process — ดึงงานสแกนจากคิวมาประมวลผลผ่าน jobs/scan_job.py
แยกออกจาก web (Bulkhead): OCR กิน CPU หนัก ไม่ให้ลาก web tier ตาย
รันเป็นคนละ process/container กับ main.py"""


def main():
    raise NotImplementedError  # TODO: loop ดึงงานจาก job_queue แล้วเรียก scan_job.run


if __name__ == "__main__":
    main()
