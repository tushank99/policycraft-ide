import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { authEnabled, getAccessToken, handleCallback, isAdmin, login } from './services/auth';
import { Shield, AlertCircle } from 'lucide-react';
import Layout from './components/Layout';
import AdminOverview from './pages/AdminOverview';
import AdminDashboard from './pages/AdminDashboard';
import DeveloperPortal from './pages/DeveloperPortal';
import DeveloperPolicyView from './pages/DeveloperPolicyView';
import NewService from './pages/NewService';
import GenerationPlanPage from './pages/GenerationPlanPage';
import GenerationStatus from './pages/GenerationStatus';
import ResultsDashboard from './pages/ResultsDashboard';
import './index.css';

function PlaceholderPage({ title, subtitle }) {
  return (
    <div className="page-body" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 400 }}>
      <div style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
        <Shield size={40} style={{ margin: '0 auto 16px', opacity: 0.3 }} />
        <div style={{ fontSize: 'var(--text-lg)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>{title}</div>
        <div style={{ fontSize: 'var(--text-sm)' }}>{subtitle}</div>
      </div>
    </div>
  );
}

function AdminDeniedModal({ onClose }) {
  return (
    <div className="modal-overlay">
      <div className="modal-card">
        <div className="modal-icon">
          <Shield size={22} />
        </div>
        <div className="modal-title">Admin Access</div>
        <div className="modal-subtitle">
          Your account is not in the <code>admins</code> group. Ask a platform admin to add you
          (aws cognito-idp admin-add-user-to-group).
        </div>
        <div className="modal-actions">
          <button type="button" className="btn btn-primary" style={{ flex: 1 }} onClick={onClose}>
            OK
          </button>
        </div>
      </div>
    </div>
  );
}

function AuthCallback() {
  const navigate = useNavigate();
  const [error, setError] = useState(null);
  useEffect(() => {
    handleCallback()
      .then((to) => navigate(to, { replace: true }))
      .catch((e) => setError(e.message));
  }, [navigate]);
  return (
    <div className="page-body" style={{ textAlign: 'center', paddingTop: 80 }}>
      {error ? (
        <div style={{ color: 'var(--error)' }}>
          <AlertCircle size={20} /> {error}{' '}
          <button className="btn btn-secondary" onClick={() => login('/')}>Try again</button>
        </div>
      ) : 'Signing you in…'}
    </div>
  );
}

function RequireLogin({ children }) {
  const location = useLocation();
  const needsLogin = authEnabled && !getAccessToken() && location.pathname !== '/auth/callback';
  useEffect(() => {
    if (needsLogin) login(location.pathname);
  }, [needsLogin, location.pathname]);
  if (needsLogin) return <div className="page-body" style={{ textAlign: 'center', paddingTop: 80 }}>Redirecting to sign in…</div>;
  return children;
}

export default function App() {
  // The UI role is only a view toggle; the API enforces admin rights (Cognito "admins" group).
  const [role, setRole] = useState(() => {
    let saved = 'developer';
    try { saved = localStorage.getItem('idp-role') || 'developer'; } catch { /* storage blocked */ }
    return saved === 'admin' && !isAdmin() ? 'developer' : saved;
  });
  const [showDenied, setShowDenied] = useState(false);

  function persistRole(newRole) {
    setRole(newRole);
    try { localStorage.setItem('idp-role', newRole); } catch { /* storage blocked */ }
  }

  function handleAdminClick() {
    if (role === 'admin') return;
    if (isAdmin()) persistRole('admin');
    else setShowDenied(true);
  }

  function handleRoleChange(newRole) {
    if (newRole === 'admin' && !isAdmin()) {
      setShowDenied(true);
      return;
    }
    persistRole(newRole);
  }

  return (
    <BrowserRouter>
      {showDenied && <AdminDeniedModal onClose={() => setShowDenied(false)} />}

      <Routes>
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="*" element={
      <RequireLogin>
      <Layout role={role} onRoleChange={handleRoleChange} onAdminClick={handleAdminClick}>
        <Routes>
          <Route path="/" element={<Navigate to={role === 'admin' ? '/admin' : '/developer/requests'} replace />} />

          {/* Admin routes */}
          <Route path="/admin" element={<AdminOverview />} />
          <Route path="/admin/policy" element={<AdminDashboard />} />
          <Route path="/admin/requests" element={<DeveloperPortal adminView />} />
          <Route path="/admin/audit" element={<PlaceholderPage title="Audit Logs" subtitle="Audit log viewer coming soon." />} />

          {/* Developer routes */}
          <Route path="/developer" element={<Navigate to="/developer/requests" replace />} />
          <Route path="/developer/requests" element={<DeveloperPortal />} />
          <Route path="/developer/compliance" element={<DeveloperPolicyView />} />
          <Route path="/developer/new" element={<NewService />} />
          <Route path="/developer/plan/:requestId" element={<GenerationPlanPage />} />
          <Route path="/developer/status/:requestId" element={<GenerationStatus />} />
          <Route path="/developer/results/:requestId" element={<ResultsDashboard />} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
      </RequireLogin>
        } />
      </Routes>
    </BrowserRouter>
  );
}
