"""
Package containing all of the scope types that the ChipWhisperer API can connect to:

Scopes:

   * OpenADC- CWLite, CWPro, and CWHusky

   * CWNano - CWNano

   * PicoScope - PicoScope (old, untested)

   * VisaScope - VisaScope (requires Visa module, old, untested)

"""
from .OpenADC import OpenADC
from .cwnano import CWNano
from .MSO4 import MSO4
from .mso4hardware.triggers import MSO4Triggers, MSO4EdgeTrigger, MSO4WidthTrigger
from typing import Union
# try:
#     from .sakura_g import SakuraG
# except:
#     pass

ScopeTypes = Union[OpenADC, CWNano, MSO4]
