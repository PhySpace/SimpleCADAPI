import { useState } from 'react';
import { ReModePage } from '../remode/ReModeWorkspace';
import { StudioPage } from '../studio/StudioPage';
import '../styles.css';

type Mode = 'studio' | 'remode';

const modeLabels: Record<Mode, string> = {
  studio: 'Studio',
  remode: 'Re-mode',
};

export function App() {
  const [mode, setMode] = useState<Mode>('studio');

  return (
    <div className="h-screen min-h-0 bg-void font-sans text-ink antialiased">
      <nav className="relative z-20 flex h-10 items-center gap-1 border-b border-line bg-panel px-4 font-mono text-[10px] text-dim" aria-label="Editor modes">
        <strong className="mr-[18px] font-sans text-[12px] font-semibold text-ink">SimpleCAD</strong>
        {(Object.keys(modeLabels) as Mode[]).map((candidate) => (
          <button
            key={candidate}
            className={`h-[26px] rounded-[3px] border px-3 font-inherit tracking-[0.06em] uppercase transition-colors hover:border-[#526d40] hover:bg-[#18221c] hover:text-lime ${mode === candidate ? 'border-[#526d40] bg-[#18221c] text-lime' : 'border-transparent text-dim'}`}
            type="button"
            aria-selected={mode === candidate}
            onClick={() => setMode(candidate)}
          >
            {modeLabels[candidate]}
          </button>
        ))}
      </nav>
      <main className="h-[calc(100vh-40px)] min-h-0">
        {mode === 'studio' ? <StudioPage /> : <ReModePage />}
      </main>
    </div>
  );
}
