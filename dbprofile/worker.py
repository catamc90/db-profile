"""Run blocking database calls off the GUI thread."""
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal


class _Signals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(object)


class _Task(QRunnable):
    def __init__(self, fn, args):
        super().__init__()
        self.fn, self.args = fn, args
        self.signals = _Signals()

    def run(self):
        try:
            try:
                result = self.fn(*self.args)
            except Exception as e:  # noqa: BLE001
                self.signals.failed.emit(e)
            else:
                self.signals.done.emit(result)
        except RuntimeError:
            pass  # the application quit while this task was running; nobody is left to notify


_active: set = set()


def run_async(fn, *args, on_done=None, on_error=None):
    """Call fn(*args) in the thread pool; callbacks run on the GUI thread."""
    task = _Task(fn, args)
    task.setAutoDelete(False)
    _active.add(task)

    def finish(cb):
        def handler(value):
            _active.discard(task)
            if cb:
                cb(value)
        return handler

    task.signals.done.connect(finish(on_done))
    task.signals.failed.connect(finish(on_error))
    QThreadPool.globalInstance().start(task)
    return task
