"""
ISA (International Standard Atmosphere) Calculator.

Provides functions for calculating atmospheric properties at various altitudes.
"""

import math
from typing import Dict, Tuple


class ISACalculator:
    """Calculator for ISA atmospheric properties."""
    
    # Physical constants
    G = 9.80665  # m/s² - gravitational acceleration
    R = 287.0528  # J/(kg·K) - gas constant for dry air
    GAMMA = 1.4  # ratio of specific heats
    
    # Sutherland's Law constants (US76 / SU2 defaults): 1.789e-5 Pa·s at 288.15 K.
    # The desktop app paired the sea-level 1.7894e-5 with a 273.11 K reference, 4% too high.
    MU_0 = 1.716e-5  # kg/(m·s) - reference dynamic viscosity at T_0
    T_0 = 273.15  # K - reference temperature
    S = 110.4  # K - Sutherland constant
    
    # ISA atmospheric layers: (h_base [km], lapse_rate [K/km], T_base [K], P_base [Pa])
    LAYERS = [
        (0, -6.5, 288.15, 101325.0),      # Troposphere
        (11, 0, 216.65, 22632.1),         # Tropopause
        (20, 1.0, 216.65, 5474.89),       # Stratosphere 1
        (32, 2.8, 228.65, 868.02),        # Stratosphere 2
        (47, 0, 270.65, 110.91),          # Stratopause
        (51, -2.8, 270.65, 66.94),        # Mesosphere 1
        (71, -2.0, 214.65, 3.96),         # Mesosphere 2
        (84.85, 0, 186.95, 0.37)          # Mesopause
    ]
    
    @staticmethod
    def calculate(altitude_km: float, mach: float, length_m: float) -> Dict[str, float]:
        """
        Calculate ISA atmospheric properties.
        
        Args:
            altitude_km: Altitude in kilometers (0-100)
            mach: Mach number
            length_m: Characteristic length in meters
            
        Returns:
            Dictionary containing:
                - temperature: Temperature [K]
                - pressure: Pressure [Pa]
                - density: Density [kg/m³]
                - dynamic_viscosity: Dynamic viscosity [kg/(m·s)]
                - kinematic_viscosity: Kinematic viscosity [m²/s]
                - true_airspeed: True airspeed [m/s]
                - dynamic_pressure: Dynamic pressure [Pa]
                - reynolds_number: Reynolds number [-]
        """
        if not 0 <= altitude_km <= 100:
            raise ValueError("Altitude must be between 0 and 100 km")
        
        # Find the appropriate atmospheric layer
        h_b, L_rate, T_b, P_b = ISACalculator.LAYERS[0]
        for layer in ISACalculator.LAYERS:
            if altitude_km >= layer[0]:
                h_b, L_rate, T_b, P_b = layer
        
        # Calculate temperature
        temperature = T_b + L_rate * (altitude_km - h_b)
        
        # Calculate pressure
        if L_rate != 0:
            pressure = P_b * (temperature / T_b) ** (
                -ISACalculator.G / (L_rate / 1000 * ISACalculator.R)
            )
        else:
            pressure = P_b * math.exp(
                -ISACalculator.G * (altitude_km - h_b) * 1000 / (ISACalculator.R * T_b)
            )
        
        # Calculate density
        density = pressure / (ISACalculator.R * temperature)
        
        # Calculate true airspeed
        speed_of_sound = math.sqrt(ISACalculator.GAMMA * ISACalculator.R * temperature)
        true_airspeed = speed_of_sound * mach
        
        # Calculate dynamic viscosity using Sutherland's Law
        dynamic_viscosity = (
            ISACalculator.MU_0 * 
            (temperature / ISACalculator.T_0) ** 1.5 * 
            (ISACalculator.T_0 + ISACalculator.S) / (temperature + ISACalculator.S)
        )
        
        # Calculate kinematic viscosity
        kinematic_viscosity = dynamic_viscosity / density
        
        # Calculate Reynolds number
        reynolds_number = (true_airspeed * length_m) / kinematic_viscosity
        
        # Calculate dynamic pressure
        dynamic_pressure = 0.5 * density * true_airspeed ** 2
        
        return {
            'temperature': temperature,
            'pressure': pressure,
            'density': density,
            'speed_of_sound': speed_of_sound,
            'dynamic_viscosity': dynamic_viscosity,
            'kinematic_viscosity': kinematic_viscosity,
            'true_airspeed': true_airspeed,
            'dynamic_pressure': dynamic_pressure,
            'reynolds_number': reynolds_number
        }
    
    @staticmethod
    def get_formulas() -> str:
        """
        Get formatted string of ISA formulas.
        
        Returns:
            HTML formatted string of formulas
        """
        return (
            "<h3>Formulas Used</h3>"
            "<p><b>Dynamic Viscosity (μ):</b><br>"
            "Sutherland's Law for temperature-dependent viscosity</p>"
            "<p><b>Kinematic Viscosity (ν):</b><br>"
            "ν = μ / ρ</p>"
            "<p><b>Reynolds Number:</b><br>"
            "Re = (V × L) / ν</p>"
            "<p><b>True Airspeed:</b><br>"
            "V = M × √(γ × R × T)</p>"
            "<p><b>Dynamic Pressure:</b><br>"
            "q = 0.5 × ρ × V²</p>"
        )
    
    @staticmethod
    def get_constants() -> str:
        """
        Get formatted string of physical constants.
        
        Returns:
            HTML formatted string of constants
        """
        return (
            "<h3>Physical Constants</h3>"
            f"<p><b>R (Gas Constant):</b> {ISACalculator.R} J/(kg·K)</p>"
            f"<p><b>g₀ (Gravity):</b> {ISACalculator.G} m/s²</p>"
            f"<p><b>γ (Gamma):</b> {ISACalculator.GAMMA}</p>"
            f"<p><b>μ₀:</b> {ISACalculator.MU_0}×10⁻⁵ kg/(m·s)</p>"
            f"<p><b>S (Sutherland):</b> {ISACalculator.S} K</p>"
            f"<p><b>T₀:</b> {ISACalculator.T_0} K</p>"
        )
