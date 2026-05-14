from pythonfmu import Fmi2Slave, Real, Boolean

class SimpleCounter(Fmi2Slave):
    """Minimal FMU: increments a counter each timestep. Used for fmpy validation."""

    author = "SVF"
    description = "Simple counter model for SVF validation"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.counter = 0.0
        self.register_variable(Real("counter", causality="output", variability="continuous"))

    def do_step(self, t, dt):
        self.counter += dt
        return True