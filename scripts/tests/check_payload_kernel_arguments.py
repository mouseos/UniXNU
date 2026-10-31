#!/usr/bin/env python3
"""Exercise real payload argument precedence and exact opt-in omission semantics."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unixnu.payload import kernel_arguments, check_args, check_confirmation_args
from unixnu.util import Error
board=['-v','serial=1','home=60','home-count=3','serial-extra=1']
assert kernel_arguments(board,[],[]) == board
assert kernel_arguments(board,['serial=2'],[]) == ['-v','home=60','home-count=3','serial-extra=1','serial=2']
assert kernel_arguments(board,[],['home','home-count']) == ['-v','serial=1','serial-extra=1']
assert kernel_arguments(board,[],['serial','serial']) == ['-v','home=60','home-count=3','serial-extra=1']
assert kernel_arguments(board,[],['missing']) == board
assert kernel_arguments(board,[],['-v']) == board[1:]
assert board == ['-v','serial=1','home=60','home-count=3','serial-extra=1']
for extra,omitted in [(['home=0'],['home']),([],['home=60']),([],['home other']),([],['']),([],['home*'])]:
 try:kernel_arguments(board,extra,omitted)
 except Error:pass
 else:raise AssertionError((extra,omitted))
assert len(check_args(['x'*1023])) == 1023
try:check_args(['x'*1024])
except Error:pass
else:raise AssertionError('command line cap lost')
check_confirmation_args('x'*1016, ['a'*6])
for bad in (['a'*7], ['☃'], [None]):
 try:check_confirmation_args('x'*1016, bad)
 except Error:pass
 else:raise AssertionError(('confirmation cap or encoding lost', bad))
print('PASS real payload argument defaults, override precedence, exact omissions, conflicts, validation, unchanged board and command-line cap')
