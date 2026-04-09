import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from '../components/Layout'
import { UploadPage } from '../features/upload/UploadPage'
import { SectionsPage } from '../features/sections/SectionsPage'
import { FindingsPage } from '../features/findings/FindingsPage'
import { ReportPage } from '../features/report/ReportPage'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<UploadPage />} />
        <Route path="/sections" element={<SectionsPage />} />
        <Route path="/findings" element={<FindingsPage />} />
        <Route path="/report" element={<ReportPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}
