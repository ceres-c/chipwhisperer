import pyvisa

from .mso4hardware.triggers import MSO4Triggers, MSO4EdgeTrigger

class MSO4:
    """Tektronix MSO 4-Series scope object.

    Attributes:
        rm: pyvisa.ResourceManager instance
        sc: pyvisa.resources.MessageBasedResource instance
        trig: MSO4Triggers type (not an instance)
        src (src): Source for the waveform data (e.g. 'CH1')
    """

    _name = "ChipWhisperer/MSO4"
    sources = ['ch1', 'ch2', 'ch3', 'ch4'] # TODO add MATH_, REF_, CH_D...
    # See programmer manual § DATa:SOUrce

    def __init__(self):
        self.rm: pyvisa.ResourceManager = None # type: ignore
        self.sc: pyvisa.resources.MessageBasedResource = None # type: ignore

        self.record_len = 0

        # Local storage for the internal trigger instance
        self._trig: MSO4Triggers = None # type: ignore

        self._src: str = None # type: ignore

        self.connectStatus = False

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
            raise IOError("Invalid IDN string returned from scope")
        return {
            'vendor': s[0],
            'model': s[1],
            'serial': s[2],
            'firmware': s[3]
        }

    def con(self, ip: str = "", trig_type: MSO4Triggers = MSO4EdgeTrigger, **kwargs) -> bool:
        """Connect to scope.

        Args:
            ip: IP address of scope
            kwargs: Additional arguments to pass to pyvisa.ResourceManager.open_resource

        Returns:
            True if successful, False otherwise

        Raises:
            ValueError: IP address must be specified
            OSError: Invalid vendor or model returned from scope
        """
        if ip == "":
            raise ValueError("IP address must be specified")

        self.rm = pyvisa.ResourceManager()
        self.sc = self.rm.open_resource(f'TCPIP::{ip}::INSTR') # type: ignore
        self.trig = trig_type

        sc_id = self._id_scope()
        if sc_id['vendor'] != 'TEKTRONIX':
            raise OSError(f'Invalid vendor returned from scope {sc_id["vendor"]}')
        if sc_id['model'] not in ['MSO44', 'MSO46']:
            raise OSError(f'Invalid model returned from scope {sc_id["model"]}')

        # Enable all events reporting in the status register
        self.sc.write('DESE 255')
        # Clear: Event Queue, Standard Event Status Register, Status Byte Register
        self.sc.write('*CLS')
        # Set waveform data format to binary (faster than ASCII)
        self.sc.write('DATa:ENCdg RFBinary') # float msb first
        # Set waveform data to 32-bit
        self.sc.write('WFMOutpre:BYT_Nr 4')
        # Get the record length
        try:
            self.record_len = int(self.sc.query('HORizontal:MODe:RECOrdlength?').strip())
        except Exception:
            self.dis()
            raise
        # Set data start and stop (retrieve all data)
        self.sc.write('DATA:START 1')
        self.sc.write(f'DATA:STOP {self.record_len}')

        self.connectStatus = True
        return True

    def dis(self) -> bool:
        """Disconnect from scope.
        """
        self.sc.close()
        self.rm.close()

        self.trig = None # type: ignore

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
            raise OSError("Scope is not connected. Connect it first...")

        try:
            self.sc.write('ACQuire:STATE 1') # Acquire one trace
        except Exception:
            self.dis()
            raise

    def capture(self):
        """Reads power trace data from the scope.

        Returns:
            False upon success and True upon failure
        """

        if not self._src:
            raise ValueError("Must set waveform source before starting capture")

        available = self.sc.query('DATa:SOUrce:AVAILable?').lower()
        if 'none' in available:
            return False

        # Read the preamble
        preamble = self.sc.query('WFMOutpre').strip() # TODO how to use this?

        # Read the data
        data = self.sc.query('CURVE?').strip()

        pass

    def get_last_trace(self):
        """Returns the scope data read by capture()

        Returns:
            A numpy array containing the scope data.
        """
        pass

    @property
    def trig(self) -> MSO4Triggers:
        return self._trig
    @trig.setter
    def trig(self, trig_type: MSO4Triggers):
        self._trig = trig_type(self.sc)

    @property
    def src(self) -> str:
        return self.sc.query('DATa:SOUrce?').strip()
    @src.setter
    def src(self, src: str):
        if src.lower() not in self.sources:
            raise ValueError(f"Invalid source {src}. Valid sources are {self.sources}")
        self._src = src
        self.sc.write(f'DATa:SOUrce {src}')
