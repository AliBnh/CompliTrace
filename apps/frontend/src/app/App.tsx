import { Navigate, Route, Routes } from 'react-router-dom'

import { useAppState } from './state'
import { Layout } from '../components/Layout'
import { LoginPage } from '../features/auth/LoginPage'
import { SignupPage } from '../features/auth/SignupPage'
import { UploadPage } from '../features/upload/UploadPage'
import { SectionsPage } from '../features/sections/SectionsPage'
import { FindingsPage } from '../features/findings/FindingsPage'
import { RemediationPage } from '../features/remediation/RemediationPage'
import { ReportPage } from '../features/report/ReportPage'

export default function App() {
  const { authLoading, token } = useAppState()
  if (authLoading) return null

  return (
    <Routes>
      <Route path="/login" element={token ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/signup" element={token ? <Navigate to="/" replace /> : <SignupPage />} />
      <Route path="/*" element={token ? <ProtectedApp /> : <Navigate to="/login" replace />} />
    </Routes>
  )
}

function ProtectedApp() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<UploadPage />} />
        <Route path="/sections" element={<SectionsPage />} />
        <Route path="/findings" element={<FindingsPage />} />
        <Route path="/remediation" element={<RemediationPage />} />
        <Route path="/report" element={<ReportPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}
