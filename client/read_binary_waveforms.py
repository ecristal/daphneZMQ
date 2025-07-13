import numpy as np
import matplotlib.pyplot as plt

def read_binary_waveforms(filename, N):
    """
    Lee waveforms desde un archivo binario uint16.

    Args:
        filename (str): Ruta al archivo binario.
        N (int): Número de muestras por waveform.

    Returns:
        np.array: Array de waveforms con forma (M, N).
    """
    data = np.fromfile(filename, dtype=np.uint16)

    if data.size % N != 0:
        raise ValueError(f"El tamaño del archivo ({data.size}) no es divisible por N ({N})")

    M = data.size // N

    waveforms = data.reshape((M, N))

    return waveforms

# Ejemplo de uso
if __name__ == "__main__":
    filename = "channel_8_clc_filter_cable.dat"  # Cambia por tu archivo binario real
    N = 2048                    # Número de muestras por waveform

    waveforms = read_binary_waveforms(filename, N)

    # Calcula y grafica el waveform promedio
    mean_waveform = waveforms.mean(axis=0)

    plt.figure(figsize=(10, 6))
    plt.plot(mean_waveform)
    plt.title("Waveform promedio")
    plt.xlabel("Muestra")
    plt.ylabel("Valor ADC (uint16)")
    plt.grid(True)
    plt.show()