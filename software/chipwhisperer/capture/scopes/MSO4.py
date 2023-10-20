import datetime
import time
from typing import Sequence

import pyvisa
import numpy

from .mso4hardware.triggers import MSO4Triggers, MSO4EdgeTrigger
from chipwhisperer.logging import scope_logger
from chipwhisperer.common.utils import util

# TODO:
# * Implement the other trigger types (mostly sequence)
# * How about rtn._getNAEUSB() called in chipwhisperer.__init__.scope()?
# * Move all waveform configuration to a separate class

class MSO4:
    """Tektronix MSO 4-Series scope object.

    Attributes:
        rm: pyvisa.ResourceManager instance
        sc: pyvisa.resources.MessageBasedResource instance
        trigger: MSO4Triggers type (not an instance)
        src (src): Source for the waveform data (e.g. 'CH1')
    """

    _name = 'ChipWhisperer/MSO4'
    sources = ['ch1', 'ch2', 'ch3', 'ch4'] # TODO add MATH_, REF_, CH_D...
    # See programmer manual § DATa:SOUrce
    modes = ['sample', 'peakdetect', 'hires', 'average', 'envelope']
    wfm_encodings = ['binary', 'ascii']
    wfm_binary_formats = ['ri', 'rp', 'fp']
    wfm_byte_nrs = [1, 2, 8] # Programmer manual § WFMOutpre:BYT_Nr
    wfm_byte_orders = ['lsb', 'msb']

    def __init__(self):
        self.rm: pyvisa.ResourceManager = None # type: ignore
        self.sc: pyvisa.resources.MessageBasedResource = None # type: ignore

        # Local storage for the internal trigger instance
        self._trig: MSO4Triggers = None # type: ignore

        self._src: str = None # type: ignore
        self._mode: str = None # type: ignore
        self._record_len: int = 0
        self._timeout: float = 2.0

        self._cached_wfm_byte_nr: int = 0
        self._cached_wfm_format: str = ''
        self._cached_wfm_order: str = ''
        self._cached_wfm_encoding: str = ''

        self.wfm_data_points: Sequence = []

        self.connectStatus = False

    def _clear_cache(self) -> None:
        """Resets the local configuration cache and fetches updated values from
        the scope.

        This is useful when the scope configuration is (potentially) changed externally.
        """
        self._cached_wfm_byte_nr = 0
        self._cached_wfm_format = ''
        self._cached_wfm_order = ''
        self._cached_wfm_encoding = ''

    def _id_scope(self) -> dict:
        """Read identification string from scope

        Raises:
            Exception: Error when arming. This method catches these and
                disconnects before reraising them.
        """

        try:
            idn = self.sc.query('*IDN?') # TEKTRONIX,MSO44,C019654,CF:91.1CT FV:2.0.3.950
        except Exception:
            self.dis()
            raise

        s = idn.split(',')
        if len(s) != 4:
            raise OSError('Invalid IDN string returned from scope')
        return {
            'vendor': s[0],
            'model': s[1],
            'serial': s[2],
            'firmware': s[3]
        }

    def con(self, sn = None, ip: str = '', trig_type: MSO4Triggers = MSO4EdgeTrigger, **kwargs) -> bool:
        """Connect to scope.

        Args:
            sn (str): Ignored, but kept for compatibility with other scopes
            ip: IP address of scope
            kwargs: Additional arguments to pass to pyvisa.ResourceManager.open_resource

        Returns:
            True if successful, False otherwise

        Raises:
            ValueError: IP address must be specified
            OSError: Invalid vendor or model returned from scope
        """
        _ = sn

        if not ip:
            raise ValueError('IP address must be specified')

        self.rm = pyvisa.ResourceManager()
        self.sc = self.rm.open_resource(f'TCPIP::{ip}::INSTR') # type: ignore
        self.trigger = trig_type

        sc_id = self._id_scope()
        if sc_id['vendor'] != 'TEKTRONIX':
            self.dis()
            raise OSError(f'Invalid vendor returned from scope {sc_id["vendor"]}')
        if sc_id['model'] not in ['MSO44', 'MSO46']:
            self.dis()
            raise OSError(f'Invalid model returned from scope {sc_id["model"]}')

        # Configure scope environment
        try:
            # Enable all events reporting in the status register
            self.sc.write('DESE 255')

            # Clear: Event Queue, Standard Event Status Register, Status Byte Register
            self.sc.write('*CLS')
        except Exception:
            self.dis()
            raise

        # Configure waveform data
        try:
            # TODO Make these configurable. kwargs maybe?
            # NOTE the DATA:ENCdg command is broken in the MSO44 firmware version 2.0.3.950
            self.wfm_encoding = 'binary'
            self.wfm_binary_format = 'ri' # Signed integer
            # NOTE floating point seems to be rejected in the MSO44 firmware version 2.0.3.950
            self.wfm_byte_order = 'lsb' # Easier to work with little endian because numpy
            self.wfm_byte_nr = 2 # 16-bit

            # Get the record length
            self._record_len = int(self.sc.query('HORizontal:MODe:RECOrdlength?').strip())

            # Set waveform start and stop (retrieve all data)
            self.sc.write('DATA:START 1')
            self.sc.write(f'DATA:STOP {self._record_len}')
        except Exception:
            self.dis()
            raise

        self.connectStatus = True
        return True

    def dis(self) -> bool:
        """Disconnect from scope.
        """
        self.sc.close()
        self.rm.close()

        self.connectStatus = False
        return True

    def arm(self) -> None:
        """Setup scope to begin capture/glitching when triggered.

        The scope must be armed before capture or glitching (when set to
        'ext_single') can begin.

        Raises:
            OSError: Scope isn't connected.
            Exception: Error when arming. This method catches these and
                disconnects before reraising them.
        """

        if self.connectStatus is False:
            raise OSError('Scope is not connected. Connect it first...')

        try:
            self.sc.write('ACQuire:STATE 1') # Acquire one trace

            for _ in range(10):
                if self.sc.query('ACQuire:STATE?').strip() == '1':
                    break
                time.sleep(0.05)
            else:
                raise OSError('Failed to arm scope')
        except Exception:
            self.dis()
            raise

    def capture(self, poll_done: bool = True):
        """Captures trace. Scope must be armed before capturing.

        Blocks until scope triggered (or times out),
        then disarms scope and copies data back.

        Read captured data out with :code:`scope.get_last_trace()`

        Args:
            poll_done: This only exists to make this function compatible
            with the capture_trace() function in the ChipWhisperer API.
            Will always poll the scope until it is done/times out.
        Returns:
           True if capture timed out, false if it didn't.

        Raises:
           IOError: Unknown failure.
        """
        _ = poll_done = True

        if not self._src:
            raise ValueError('Must set waveform source before starting capture')
        if not all([self.wfm_byte_nr, self.wfm_binary_format, self.wfm_byte_order, self.wfm_encoding]):
            raise ValueError('Must arm scope before starting capture')

        timeout = False
        starttime = datetime.datetime.now()

        # Wait for a trigger
        while 'armed' in self.sc.query('TRIGger:STATE?').lower():
            diff = datetime.datetime.now() - starttime
            # If we've timed out, don't wait any longer for a trigger
            if (diff.total_seconds() > self._timeout):
                scope_logger.warning('Timeout in MSO4 capture(), no trigger seen! Trigger forced, data is invalid.')
                timeout = True
                self.sc.write('TRIGger FORCe')
                break

        # Wait for the data to be available
        while 'none' in self.sc.query('DATa:SOUrce:AVAILable?').lower():
            diff = datetime.datetime.now() - starttime
            if (diff.total_seconds() > self._timeout):
                scope_logger.warning('Timeout in MSO4 capture() waiting for DATa:SOUrce:AVAILable.')
                timeout = True
                return timeout
        # If there is data available...

        # Got these from the programmer manual § WFMOutpre:BN_Fmt
        types = {
            1: {'ri': 'b', 'rp': 'B'},
            2: {'ri': 'h', 'rp': 'H'},
            4: {'ri': 'i', 'rp': 'I', 'fp': 'f'},
            8: {'ri': 'q', 'rp': 'Q', 'fp': 'd'},
        }

        # Read the data
        if self.wfm_encoding == 'binary':
            self.wfm_data_points = self.sc.query_binary_values(
                'CURVE?',
                datatype = types[self.wfm_byte_nr][self.wfm_binary_format],
                is_big_endian = self.wfm_byte_order == 'msb',
                container=numpy.array
            )
        else:
            raise IOError('Unknown data encoding')
            # TODO implement ASCII encoding
            # values = self.sc.query('CURVE?').strip()

        return timeout

    def get_last_trace(self, as_int: bool = False):
        """Returns the scope data read by capture()

        Returns:
            A numpy array containing the scope data.
        """
        return self.wfm_data_points

    getLastTrace = util.camel_case_deprecated(get_last_trace)

    @property
    def trigger(self) -> MSO4Triggers:
        return self._trig
    @trigger.setter
    def trigger(self, trig_type: MSO4Triggers):
        self._trig = trig_type(self.sc)

    @property
    def src(self) -> str:
        return self.sc.query('DATa:SOUrce?').strip()
    @src.setter
    def src(self, value: str):
        if value.lower() not in self.sources:
            raise ValueError(f'Invalid source {value}. Valid sources are {self.sources}')
        self._src = value
        self.sc.write(f'DATa:SOUrce {value}')

    @property
    def mode(self) -> str:
        """The acquisition mode of the scope.

        :Getter: Return the acquisition mode (str)

        :Setter: Set the acquisition mode. Valid modes are:
            * 'sample': SAMple specifies that the displayed data point value is the
            sampled value that is taken during the acquisition interval
            * 'peakdetect': PEAKdetect specifies the display of high-low range of the
            samples taken from a single waveform acquisition.
            * 'hires': HIRes specifies Hi Res mode where the displayed data point
            value is the average of all the samples taken during the acquisition interval
            * 'average': AVErage specifies averaging mode, in which the resulting
            waveform shows an average of SAMple data points from several separate
            waveform acquisitions.
            * 'envelope': ENVelope specifies envelope mode, where the resulting waveform
            displays the range of PEAKdetect from continued waveform acquisitions.
        """
        return self.sc.query('ACQuire:MODe?').strip()
    @mode.setter
    def mode(self, value: str):
        if value.lower() not in self.modes:
            raise ValueError(f'Invalid mode {value}. Valid modes are {self.modes}')
        self._mode = value
        self.sc.write(f'ACQuire:MODe {value}')

    @property
    def timeout(self) -> float:
        """The number of seconds to wait before aborting a capture.

        If no trigger event is detected before this time limit is up, the
        capture fails and no data is returned.

        :Getter: Return the number of seconds before a timeout (float)

        :Setter: Set the timeout in seconds
        """
        return self._timeout
    @timeout.setter
    def timeout(self, value: float):
        self._timeout = value

    @property
    def wfm_encoding(self) -> str:
        """The encoding of the waveform data.

        :Getter: Return the encoding (str)

        :Setter: Set the encoding. Valid values are:
            * 'binary': Binary
            * 'ascii': ASCII

        Raises:
            ValueError: Invalid encoding
        """
        if not self._cached_wfm_encoding:
            self._cached_wfm_encoding = self.sc.query('WFMOutpre:ENCdg?').strip().lower()
        return self._cached_wfm_encoding
    @wfm_encoding.setter
    def wfm_encoding(self, value: str):
        if value.lower() not in self.wfm_encodings:
            raise ValueError(f'Invalid encoding {value}. Valid encodings are {self.wfm_encodings}')
        if self._cached_wfm_encoding == value:
            return
        self._cached_wfm_encoding = value
        self.sc.write(f'WFMOutpre:ENCdg {value}')

    @property # WFMOutpre:BN_Fmt
    def wfm_binary_format(self) -> str:
        """The data format of binary waveform data.

        :Getter: Return the data format (str)

        :Setter: Set the data format. Valid values are:
            * 'ri': Signed integer
            * 'rp': Unsigned integer
            * 'fp': Floating point

        Raises:
            ValueError: Invalid data format
        """
        if not self._cached_wfm_format:
            self._cached_wfm_format = self.sc.query('WFMOutpre:BN_Fmt?').strip().lower()
        return self._cached_wfm_format
    @wfm_binary_format.setter
    def wfm_binary_format(self, value: str):
        if value.lower() not in self.wfm_binary_formats:
            raise ValueError(f'Invalid binary format {value}. Valid binary formats are {self.wfm_binary_formats}')
        if self._cached_wfm_format == value:
            return
        self._cached_wfm_format = value
        self.sc.write(f'WFMOutpre:BN_Fmt {value}')

    @property
    def wfm_byte_nr(self) -> int:
        """The number of bytes per data point in the waveform.

        :Getter: Return the number of bytes per data point (int)

        :Setter: Set the number of bytes per data point (int)
            NOTE: Check the programmer manual for valid values § WFMOutpre:BYT_Nr. If unsure, clear the cache with :code:`scope._clear_cache()` and read back the value
        """
        if not self._cached_wfm_byte_nr:
            self._cached_wfm_byte_nr = int(self.sc.query('WFMOutpre:BYT_Nr?').strip())
        return self._cached_wfm_byte_nr
    @wfm_byte_nr.setter
    def wfm_byte_nr(self, value: int):
        if not isinstance(value, int):
            raise ValueError(f'Invalid number of bytes per data point {value}. Must be an int.')
        if value not in self.wfm_byte_nrs:
            raise ValueError(f'Invalid number of bytes per data point {value}. Valid values are {self.wfm_byte_nrs}')
        if self._cached_wfm_byte_nr == value:
            return
        self._cached_wfm_byte_nr = value
        self.sc.write(f'WFMOutpre:BYT_Nr {value}')

    @property
    def wfm_byte_order(self) -> str:
        """The byte order of the waveform data.

        :Getter: Return the byte order (str)

        :Setter: Set the byte order. Valid values are:
            * 'lsb': Least significant byte first
            * 'msb': Most significant byte first

        Raises:
            ValueError: Invalid byte order
        """
        if not self._cached_wfm_order:
            self._cached_wfm_order = self.sc.query('WFMOutpre:BYT_Or?').strip().lower()
        return self._cached_wfm_order
    @wfm_byte_order.setter
    def wfm_byte_order(self, value: str):
        if value.lower() not in self.wfm_byte_orders:
            raise ValueError(f'Invalid byte order {value}. Valid byte orders are {self.wfm_byte_orders}')
        if self._cached_wfm_order == value:
            return
        self._cached_wfm_order = value
        self.sc.write(f'WFMOutpre:BYT_Or {value}')
