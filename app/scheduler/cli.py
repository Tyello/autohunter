import time
from app.scheduler.run import start_scheduler
from app.scheduler.worker_threads import stop_worker_threads

def main():
    sched = start_scheduler()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sched.shutdown(wait=False)
        stop_worker_threads(timeout=10)

if __name__ == "__main__":
    main()
