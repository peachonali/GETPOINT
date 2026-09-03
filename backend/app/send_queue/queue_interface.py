"""สัญญา (Port) ของคิวส่งขาออก — วันหน้าเปลี่ยน DB-table → SQS/Redis ไม่ต้องรื้อ"""
from abc import ABC, abstractmethod


class QueuePort(ABC):
    @abstractmethod
    def enqueue(self, job) -> None:
        raise NotImplementedError

    @abstractmethod
    def dequeue(self):
        raise NotImplementedError
