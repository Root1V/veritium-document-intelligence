import { Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from '@/components/layout/ProtectedRoute'
import { RequireRole } from '@/components/layout/RequireRole'
import { LoginPage } from '@/pages/Login'
import { DashboardPage } from '@/pages/Dashboard'
import { UploadPage } from '@/pages/Upload'
import { BatchDetailPage } from '@/pages/BatchDetail'
import { DocumentDetailPage } from '@/pages/DocumentDetail'
import { ReviewQueuePage } from '@/pages/ReviewQueue'
import { TypeSuggestionsPage } from '@/pages/TypeSuggestions'
import { DocumentTypesPage } from '@/pages/DocumentTypes'
import { NewDocumentTypePage } from '@/pages/NewDocumentType'
import { AuditPage } from '@/pages/Audit'
import { DocumentsPage } from '@/pages/Documents'
import { UsersPage } from '@/pages/Users'
import { ValidationPage } from '@/pages/Validation'
import { ValidationRulesPage } from '@/pages/ValidationRules'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <DashboardPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/upload"
        element={
          <ProtectedRoute>
            <RequireRole roles={['operador', 'admin']}>
              <UploadPage />
            </RequireRole>
          </ProtectedRoute>
        }
      />
      <Route
        path="/batches/:batchId"
        element={
          <ProtectedRoute>
            <BatchDetailPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/documents"
        element={
          <ProtectedRoute>
            <DocumentsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/documents/:documentId"
        element={
          <ProtectedRoute>
            <DocumentDetailPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/review"
        element={
          <ProtectedRoute>
            <ReviewQueuePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/type-suggestions"
        element={
          <ProtectedRoute>
            <TypeSuggestionsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/document-types"
        element={
          <ProtectedRoute>
            <DocumentTypesPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/document-types/new"
        element={
          <ProtectedRoute>
            <RequireRole roles={['admin']}>
              <NewDocumentTypePage />
            </RequireRole>
          </ProtectedRoute>
        }
      />
      <Route
        path="/audit"
        element={
          <ProtectedRoute>
            <AuditPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/users"
        element={
          <ProtectedRoute>
            <RequireRole roles={['admin']}>
              <UsersPage />
            </RequireRole>
          </ProtectedRoute>
        }
      />
      <Route
        path="/validation"
        element={
          <ProtectedRoute>
            <ValidationPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/validation-rules"
        element={
          <ProtectedRoute>
            <ValidationRulesPage />
          </ProtectedRoute>
        }
      />
    </Routes>
  )
}
