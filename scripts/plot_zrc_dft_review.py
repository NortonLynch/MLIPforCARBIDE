"""Plot the reviewed calibration data; does not run DFT or MACE inference."""
from pathlib import Path
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'dft/reviews/dft600-k67-20261008'


def main():
    comparison = json.loads((DEST / 'mace/mace-vs-DFT36.json').read_text())
    audit = json.loads((DEST / 'summary.json').read_text())
    assert audit['all_numerical_integrity_checks_pass']
    assert audit['all_pair_budgets_pass']
    rows = [r for r in comparison['comparisons'] if r['kmesh'] == 7]
    assert len(rows) == 18
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False,
                         'axes.spines.right': False, 'savefig.dpi': 180})
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), layout='constrained')
    for vol, color, marker in [(0.95, '#276A91', 'o'), (1.0, '#D68127', 's'), (1.05, '#45917B', '^')]:
        subset = sorted([r for r in rows if r['volume_scale'] == vol], key=lambda r:r['target_temperature_K'])
        x = [r['target_temperature_K'] for r in subset]
        quantities = [
            [r['reference01_aligned_mace_minus_DFT_energy_meV_atom']['e_fr_energy'] for r in subset],
            [r['force_component_RMSE_eV_A'] for r in subset],
            [100*r['force_relative_RMSE'] for r in subset],
        ]
        for ax, y in zip(axes, quantities):
            ax.plot(x, y, color=color, marker=marker, linewidth=1.1, markersize=6,
                    label=f'{vol:.2f} V_start')
    titles = ['Energy error, one common reference', 'Force error', 'Force error relative to DFT force scale']
    ylabels = ['MACE - DFT relative energy (meV/atom)', 'Force-component RMSE (eV/Angstrom)', 'RMSE / RMS(DFT force components) (%)']
    for ax, title, ylabel in zip(axes, titles, ylabels):
        ax.set_title(title, fontsize=11, pad=12)
        ax.set_ylabel(ylabel)
        ax.set_xlabel('Parent MD target temperature (K)')
        ax.set_xticks([300,1500,3000,4500,5250,6000], ['300','1500','3000','4500','5250','6000'], rotation=35)
        ax.grid(alpha=.18)
        ax.margins(x=.06)
    axes[0].axhline(0, color='#777777', lw=.8)
    axes[1].axhline(audit['maxima']['force_component_RMS_eV_A']['value'], color='#666666',
                    ls=':', lw=1, label='Largest k6-k7 force RMS')
    axes[1].set_ylim(bottom=0)
    axes[2].set_ylim(bottom=0)
    axes[0].legend(frameon=False, fontsize=9, loc='lower left')
    axes[1].legend(handles=axes[1].get_legend_handles_labels()[0][-1:], frameon=False,
                   fontsize=8, loc='upper left')
    fig.suptitle('18 calibration frames: MACE-MH-1 / omat_pbe vs PBE, 600 eV, Gamma 7 x 7 x 7', fontsize=13)
    fig.savefig(DEST / 'mace-calibration-comparison.png')
    fig.savefig(DEST / 'mace-calibration-comparison.pdf')
    plt.close(fig)

    keys = list(audit['tolerances'])
    ratios = np.array([abs(audit['maxima'][k]['value'])/audit['tolerances'][k] for k in keys])
    fig, ax = plt.subplots(figsize=(8, 3.7), layout='constrained')
    bars = ax.barh(['Relative energy', 'Force-component RMS', 'Maximum force component', 'Maximum stress component'],
                  ratios, color='#327D9A', height=.58)
    ax.axvline(1, ls='--', lw=1.2, color='#A94945', label='Project tolerance')
    ax.set_xlim(0, 1.1)
    ax.invert_yaxis()
    ax.set_xlabel('Largest difference over 18 pairs / project tolerance')
    ax.set_title('k6 versus k7 at 600 eV: all 18 pairs pass all four budgets', pad=12)
    for bar, ratio in zip(bars, ratios):
        ax.text(ratio+.02, bar.get_y()+bar.get_height()/2, f'{100*ratio:.1f}%', va='center')
    ax.legend(frameon=False, loc='lower right')
    fig.savefig(DEST / 'kmesh-tolerance-comparison.png')
    fig.savefig(DEST / 'kmesh-tolerance-comparison.pdf')
    plt.close(fig)


if __name__ == '__main__':
    main()
