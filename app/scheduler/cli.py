import time
from app.scheduler.run import start_scheduler

def main():
    sched = start_scheduler()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sched.shutdown(wait=False)

if __name__ == "__main__":
    main()
