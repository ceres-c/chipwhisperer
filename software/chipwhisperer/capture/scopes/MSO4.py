import datetime
import time
from typing import Sequence

import pyvisa
import numpy

from pyvisa import constants

from .mso4hardware.triggers import MSO4Triggers, MSO4EdgeTrigger
from .mso4hardware.acquisition import MSO4Acquisition
from .mso4hardware.channel import MSO4AnalogChannel
from chipwhisperer.logging import scope_logger
from chipwhisperer.common.utils import util

# TODO:
# * Enable/disable channels
# * Implement the other trigger types (mostly sequence)
# * How about rtn._getNAEUSB() called in chipwhisperer.__init__.scope()?
# * Change binary format to 8 bit when in low res mode?
# * Add note about starting off with a freshly booted machine to avoid issues
# * Add note in readme about "smart" Dell docking stations and ethernet

class MSO4:
    '''Tektronix MSO 4-Series scope object. This is not usable until `con()` is called.

    Attributes:
        rm: pyvisa.ResourceManager instance
        sc: pyvisa.resources.MessageBasedResource instance
        ch_a (list):  1-based list of MSO4AnalogChannel instances
        trigger: MSO4Triggers type (not an instance)
    '''

    _name = 'ChipWhisperer/MSO4'
    sources = ['ch1', 'ch2', 'ch3', 'ch4'] # TODO add MATH_, REF_, CH_D...
    # See programmer manual § DATa:SOUrce

    def __init__(self):
        self.rm: pyvisa.ResourceManager = None # type: ignore
        self.sc: pyvisa.resources.MessageBasedResource = None # type: ignore

        # Local storage for the internal trigger instance
        self._trig: MSO4Triggers = None # type: ignore
        self.acq: MSO4Acquisition = None # type: ignore

        self.ch_a: list[MSO4AnalogChannel] = []
        self.ch_a.append(None) # Dummy channel to make indexing easier # type: ignore

        self.wfm_data_points: Sequence = []

        self.connectStatus = False

    def clear_cache(self) -> None:
        '''Resets the local configuration cache so that values will be fetched from
        the scope.

        This is useful when the scope configuration is (potentially) changed externally.
        '''
        self._trig.clear_caches()
        self.acq.clear_caches()
        for ch in self.ch_a:
            ch.clear_caches()
        self.wfm_data_points = []

    def _id_scope(self) -> dict:
        '''Read identification string from scope

        Raises:
            Exception: Error when arming. This method catches these and
                disconnects before reraising them.
        '''

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

    def con(self, sn = None, ip: str = '', trig_type: MSO4Triggers = MSO4EdgeTrigger, socket: bool = True, display: bool = True, **kwargs) -> bool:
        '''Connect to scope and set default configuration:
            - timeout = 2000 ms
            - single sequence mode
            - event reporting enabled on all events
            - clear event queue, standard event status register, status byte register
            - waveform start = 1
            - waveform length = max (record length)
            - waveform encoding = binary
            - waveform binary format = signed integer
            - waveform byte order = lsb
            - waveform byte number = 2

        Args:
            sn (str): Ignored, but kept for compatibility with other scopes
            ip (str): IP address of scope
            socket (bool): Use socket connection instead of VISA
            display (bool): Enable/disable waveform display on scope
            kwargs: Additional arguments to pass to pyvisa.ResourceManager.open_resource

        Returns:
            True if successful, False otherwise

        Raises:
            ValueError: IP address must be specified
            OSError: Invalid vendor or model returned from scope
        '''
        _ = sn

        if not ip:
            raise ValueError('IP address must be specified')

        self.rm = pyvisa.ResourceManager()
        if socket:
            self.sc = self.rm.open_resource(f'TCPIP::{ip}::4000::SOCKET') # type: ignore
            self.sc.read_termination = '\n'
            self.sc.write_termination = '\n'
        else:
            self.sc = self.rm.open_resource(f'TCPIP::{ip}::INSTR') # type: ignore
        self.sc.clear() # Clear buffers

        sc_id = self._id_scope()
        if sc_id['vendor'] != 'TEKTRONIX':
            self.dis()
            raise OSError(f'Invalid vendor returned from scope {sc_id["vendor"]}')
        if sc_id['model'] not in ['MSO44', 'MSO46']:
            self.dis()
            raise OSError(f'Invalid model returned from scope {sc_id["model"]}')

        # Set visa timeout
        self.timeout = 2000 # ms

        # Init additional scope classes
        self.trigger = trig_type
        self.acq = MSO4Acquisition(self.sc)
        ch_a_num = int(sc_id['model'][-1]) # Hacky, I know, but even Tektronix people suggest it
        # Source: https://forum.tek.com/viewtopic.php?f=568&t=135345
        for ch_a in range(ch_a_num):
            self.ch_a.append(MSO4AnalogChannel(self.sc, ch_a + 1))

        # Configure scope environment
        try:
            # Enable all events reporting in the status register
            self.sc.write('DESE 255')

            # Clear: Event Queue, Standard Event Status Register, Status Byte Register
            self.sc.write('*CLS')

            # Set single sequence mode
            self.acq.stop_after = 'sequence'
            self.acq.num_seq = 1

            # Configure waveform data
            # NOTE the DATA:ENCdg command is broken in the MSO44 firmware version 2.0.3.950
            self.acq.wfm_encoding = 'binary'
            self.acq.wfm_binary_format = 'ri' # Signed integer
            # NOTE floating point seems to be rejected in the MSO44 firmware version 2.0.3.950
            self.acq.wfm_byte_order = 'lsb' # Easier to work with little endian because numpy
            self.acq.wfm_byte_nr = 2 # 16-bit

            # Set waveform start and stop (retrieve all data)
            self.acq.wfm_start = 1
            self.acq.wfm_stop = self.acq.horiz_record_length

            # Turn off waveform display
            # Or else the scope will simply DIE after ~20 captures (:
            self.acq.display = display

            # TODO set acquisition mode to single/sequence
        except Exception:
            self.dis()
            raise

        self.connectStatus = True
        return True

    def dis(self) -> bool:
        '''Disconnect from scope.
        '''
        # Re enable waveform display
        self.acq.display = True

        self.sc.close()
        self.rm.close()

        self.connectStatus = False
        return True

    def arm(self) -> None:
        '''Setup scope to begin capture/glitching when triggered.

        The scope must be armed before capture or glitching (when set to
        'ext_single') can begin.

        Raises:
            OSError: Scope isn't connected.
            Exception: Error when arming. This method catches these and
                disconnects before reraising them.
        '''

        if self.connectStatus is False:
            raise OSError('Scope is not connected. Connect it first...')

        try:
            self.sc.write('ACQuire:STATE 1') # Acquire one trace

            # Wait for the scope to arm
            for _ in range(10):
                state = self.sc.query('ACQuire:STATE?').strip()
                if '1' in state:
                    # But is it really armed? Read at the end of the function...
                    break
                time.sleep(0.05)
            else:
                raise OSError('Failed to arm scope')
        except Exception:
            self.dis()
            raise
        time.sleep(0.05) # Wait for the scope to *actually* arm
        # Tektronix is playing games with us

    def capture(self, poll_done: bool = True):
        '''Captures trace. Scope must be armed before capturing.

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
        '''
        _ = poll_done

        self.acq.configured() # Check that the scope is configured

        timeout = False
        starttime = datetime.datetime.now()
        self.starttime = starttime # TODO remove

        # Got these from the programmer manual § WFMOutpre:BN_Fmt
        types = {
            1: {'ri': 'b', 'rp': 'B'},
            2: {'ri': 'h', 'rp': 'H'},
            4: {'ri': 'i', 'rp': 'I', 'fp': 'f'},
            8: {'ri': 'q', 'rp': 'Q', 'fp': 'd'},
        }

        # Wait for a trigger
        while 'armed' in self.sc.query('TRIGger:STATE?').lower():
            diff = datetime.datetime.now() - starttime
            # If we've timed out, don't wait any longer for a trigger
            if diff.total_seconds() > (self.timeout / 1000):
                scope_logger.warning('Timeout in MSO4 capture(), no trigger seen! Trigger forced, data is invalid.')
                timeout = True
                self.sc.write('TRIGger FORCe')
                break
        self.armtime = datetime.datetime.now() # TODO remove

        # Wait for the data to be available
        while 'none' in self.sc.query('DATa:SOUrce:AVAILable?').lower():
            diff = datetime.datetime.now() - starttime
            if diff.total_seconds() > (self.timeout / 1000):
                scope_logger.warning('Timeout in MSO4 capture() waiting for DATa:SOUrce:AVAILable.')
                timeout = True
                return timeout
        # If there is data available...
        self.availabletime = datetime.datetime.now() # TODO remove

        # Read the data
        try:
            if self.acq.wfm_encoding == 'binary':
                self.wfm_data_points = self.sc.query_binary_values(
                    'CURVE?',
                    datatype = types[self.acq.wfm_byte_nr][self.acq.wfm_binary_format],
                    is_big_endian = self.acq.wfm_byte_order == 'msb',
                    container=numpy.array
                )
            else:
                raise IOError('Unknown data encoding')
                # TODO implement ASCII encoding
                # values = self.sc.query('CURVE?').strip()
        except pyvisa.errors.VisaIOError as e:
            if e.error_code == constants.StatusCode.error_timeout:
                timeout = True
            else:
                raise
        self.endtime = datetime.datetime.now() # TODO remove

        return timeout

    def get_last_trace(self, as_int: bool = False):
        '''Returns the scope data read by capture()

        Returns:
            A numpy array containing the scope data.
        '''
        return self.wfm_data_points

    getLastTrace = util.camel_case_deprecated(get_last_trace)

    def ch_a_enable(self, value: list[bool]) -> None:
        '''Convenience function to enable/disable analog channels.
        Will start at channel 1 and enable/disable as many channels as
        there are values in the list.'''
        for i in range(0, min(len(value), self.ch_a_num)):
            self.ch_a[i + 1].enable = value[i]

    @property
    def trigger(self) -> MSO4Triggers:
        '''Current trigger object instance.

        :Getter: Return the current trigger object instance (MSO4Triggers)

        :Setter: Instantiate a new trigger object given a MSO4Triggers type.
            Also configures the scope accordingly.
        '''
        return self._trig
    @trigger.setter
    def trigger(self, trig_type: MSO4Triggers):
        self._trig = trig_type(self.sc)

    @property
    def timeout(self) -> float:
        '''Timeout (in ms) for each VISA operation, including the CURVE? query.

        :Getter: Return the number of milliseconds before a timeout (float)

        :Setter: Set the timeout in milliseconds (float)
        '''
        return self.sc.timeout
    @timeout.setter
    def timeout(self, value: float):
        self.sc.timeout = value

    @property
    def ch_a_num(self) -> int:
        '''Number of analog channels on the scope.

        :Getter: Return the number of analog channels (int)
        '''
        return len(self.ch_a) - 1
