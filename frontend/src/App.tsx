import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'

import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Spinner from './components/Spinner'

// Code-splitting per halaman: tiap halaman dimuat saat diakses (bundle awal kecil).
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Admin = lazy(() => import('./pages/Admin'))
const Alerts = lazy(() => import('./pages/Alerts'))
const JobDetail = lazy(() => import('./pages/JobDetail'))
const Jobs = lazy(() => import('./pages/Jobs'))
const Login = lazy(() => import('./pages/Login'))
const Landing = lazy(() => import('./pages/Landing'))
const Monitor = lazy(() => import('./pages/Monitor'))
const NotFound = lazy(() => import('./pages/NotFound'))
const Profile = lazy(() => import('./pages/Profile'))
const Report = lazy(() => import('./pages/Report'))
const Storage = lazy(() => import('./pages/Storage'))
const Submit = lazy(() => import('./pages/Submit'))
const UserReportPage = lazy(() => import('./pages/UserReportPage'))
const Users = lazy(() => import('./pages/Users'))

function FullScreenLoader() {
  return (
    <div className="grid min-h-screen place-items-center">
      <Spinner label="Memuat…" />
    </div>
  )
}

export default function App() {
  return (
    <Suspense fallback={<FullScreenLoader />}>
      <Routes>
        <Route path="/welcome" element={<Landing />} />
      <Route path="/login" element={<Login />} />

        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<Dashboard />} />
          <Route path="/monitor" element={<Monitor />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:id" element={<JobDetail />} />
          <Route path="/storage" element={<Storage />} />
          <Route path="/submit/:source" element={<Submit />} />
          <Route path="/users" element={<Users />} />
          <Route path="/report" element={<Report />} />
          <Route path="/report/user/:username" element={<UserReportPage />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/profile" element={<Profile />} />
        </Route>

        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  )
}
