import { createRoot } from 'react-dom/client';
import { App } from './App';

const root = document.querySelector<HTMLDivElement>('#app');
if (!root) throw new Error('app root is missing');

createRoot(root).render(<App />);
