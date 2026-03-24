// SCADA GPU v5.0 — Vite entry point
// CSS imports (split by module)
import './styles/variables.css';
import './styles/base.css';
import './styles/sidebar.css';
import './styles/dashboard.css';
import './styles/modals.css';
import './styles/login.css';
import './styles/sanek.css';
import './styles/tasks.css';
import './styles/archive.css';
import './styles/alarms.css';
import './styles/economics.css';
import './styles/responsive.css';

// Modular orchestrator (imports all feature modules + wires window exports)
import './legacy.js';

// Init typing detection for Sanek
if (typeof window._snInitTypingDetection === 'function') {
  window._snInitTypingDetection();
}
