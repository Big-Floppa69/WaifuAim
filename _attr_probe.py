from PyQt6.QtWidgets import QApplication, QLabel
import sys

app = QApplication(sys.argv)
l = QLabel('x')
try:
    setattr(l, '_zzz_test_attr', 123)
    print('setattr ok, value:', getattr(l, '_zzz_test_attr'))
except Exception as e:
    print('setattr FAILED:', repr(e))

# Also test Qt dynamic property
try:
    l.setProperty('_zzz_test_prop', 456)
    print('setProperty ok, value:', l.property('_zzz_test_prop'))
except Exception as e:
    print('setProperty FAILED:', repr(e))
