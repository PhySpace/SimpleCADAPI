import './remode.css';

import { createRoot } from 'react-dom/client';
import { ReStudio } from './App';

const app = document.querySelector<HTMLDivElement>('#app');
if (!app) throw new Error('re-mode root is missing');

createRoot(app).render(<ReStudio />);
