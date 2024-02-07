import pyvisa as visa
import chipwhisperer as cw
import time

TIMEOUT = 20000
TIMEOUT_SHORT = 200 # Used when running the acquisition loop and don't want to waste time on a missed trigger

print("set up VISA connection")

rm = visa.ResourceManager()

scope_address = "TCPIP0::192.168.1.140::inst0::INSTR"

scope: visa.resources.MessageBasedResource = rm.open_resource(scope_address) # type: ignore
scope.timeout = TIMEOUT

print("reset scope")
scope.write("*RST")
scope.write("*CLS")

#turn off all the waveform displays
print("turn off waveform display")
scope.write("display:waveform 0")

print("set up scope")

scope.write("CH1:SCAle 1")

scope.write("HORizontal:MODe manual")
scope.write("HORizontal:MODe:SAMPlerate 6.25e9")
scope.write('HORizontal:SCAle 200e-9')
scope.write('HORizontal:POSition 10')

scope.write("TRIGger:A:TYPe EDGE")
scope.write("TRIGger:A:EDGE:SOURce CH1")
scope.write("TRIGger:A:LEVEL:CH1 1.4")
scope.write("TRIGger:A:EDGE:SLOPe RISE")
scope.write("TRIGger:A:MODe NORMAL")

scope.write("ACQuire:FASTAcq:STATE ON")
scope.write("CURVEStream?")

# Configure the target
# On the CW305, setting force=False only programs the FPGA if it is currently unprogrammed, whereas force=True programs the FPGA regardless.
# This option isn't available on the CW312T_A35 or CW312T_ICE40.
fpga_id = '100t'
target = cw.target(None, cw.targets.CW305, force=True, fpga_id=fpga_id)

# run at 10 MHz:
target.pll.pll_outfreq_set(10E6, 1)

# Acquire 1000 traces
traces = []
skipped = False # Used to simulate a "glitch" in the trigger signal
# scope.write("display:waveform 1")
# Enable curvestream mode
scope.timeout = TIMEOUT_SHORT # Reduce timeout here in case we miss a trigger
for i in range(100):
    print(i, end="\r", flush=True)
    if not (i == 32 and not skipped):
        skipped = True
        target.simpleserial_write('p', b'\x00' * 16)
        response = target.simpleserial_read('r', target.output_len, ack=True)
    try:
        trace = scope.read_raw()
    except visa.errors.VisaIOError as e:
        if e.error_code == visa.constants.VI_ERROR_TMO:
            print("Timeout occurred")
            i -= 1
            continue
    if traces and trace == traces[-1]:
        print("Duplicate trace detected")
    traces.append(trace)
scope.timeout = TIMEOUT # Reset timeout

print(len(traces))
scope.write("*CLS")
