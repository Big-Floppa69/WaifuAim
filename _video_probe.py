import os
from PyQt6.QtCore import QCoreApplication, QTimer, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink

mp4 = os.path.abspath('display_images/miyabi-hoshimi-miyabi.mp4')
print('mp4 exists:', os.path.exists(mp4), mp4)

app = QCoreApplication([])
audio = QAudioOutput()
try:
    audio.setVolume(0.0)
except Exception:
    pass

sink = QVideoSink()
player = QMediaPlayer()
player.setAudioOutput(audio)
player.setVideoOutput(sink)

state = {'frames': 0, 'null': 0}


def on_frame(frame):
    state['frames'] += 1
    try:
        img = frame.toImage()
    except Exception as e:
        print('toImage exception:', repr(e))
        img = None

    is_null = (img is None) or getattr(img, 'isNull', lambda: True)()
    if is_null:
        state['null'] += 1

    if state['frames'] in (1, 2, 3, 10, 30):
        if is_null:
            print('frame', state['frames'], 'img_null', True)
        else:
            print('frame', state['frames'], 'img_null', False, 'size', img.width(), img.height())


def on_error(err):
    try:
        print('errorOccurred:', err, player.errorString())
    except Exception:
        print('errorOccurred:', err)


try:
    player.errorOccurred.connect(on_error)
except Exception:
    pass

sink.videoFrameChanged.connect(on_frame)

player.setSource(QUrl.fromLocalFile(mp4))
player.play()

QTimer.singleShot(3500, app.quit)
app.exec()

print('frames:', state['frames'], 'null_images:', state['null'])
