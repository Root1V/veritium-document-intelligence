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
import { SemanticCatalogPage } from '@/pages/SemanticCatalog'
import { ProfilesPage } from '@/pages/Profiles'
import { ApiClientsPage } from '@/pages/ApiClients'
import { BulkJobDetailPage, BulkJobsPage } from '@/pages/BulkJobs'
import { CasesPage } from '@/pages/Cases'
import { CaseDetailPage } from '@/pages/CaseDetail'
import { ProfileEditorPage } from '@/pages/ProfileEditor'
import { AuditPage } from '@/pages/Audit'
import { DocumentsPage } from '@/pages/Documents'
import { UsersPage } from '@/pages/Users'
import { ValidationPage } from '@/pages/Validation'
import { ValidationRulesPage } from '@/pages/ValidationRules'
import { EvaluationPage } from '@/pages/Evaluation'
import { EvaluationSuitePage } from '@/pages/EvaluationSuite'
import { CalibrationPage } from '@/pages/Calibration'
import { SimulationsPage } from '@/pages/Simulations'
import { LensesPage } from '@/pages/Lenses'
import { PromptsPage } from '@/pages/Prompts'
import { UploadSessionPage } from '@/pages/UploadSession'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* Public: whoever has the link uploads (VRT-47). */}
      <Route path="/carga/:sessionId" element={<UploadSessionPage />} />
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
        path="/cases"
        element={
          <ProtectedRoute>
            <CasesPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/cases/:caseId"
        element={
          <ProtectedRoute>
            <CaseDetailPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/sistemas"
        element={
          <ProtectedRoute>
            <ApiClientsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/bulk"
        element={
          <ProtectedRoute>
            <BulkJobsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/bulk/:jobId"
        element={
          <ProtectedRoute>
            <BulkJobDetailPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/profiles"
        element={
          <ProtectedRoute>
            <ProfilesPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/profiles/new"
        element={
          <ProtectedRoute>
            <RequireRole roles={['admin']}>
              <ProfileEditorPage />
            </RequireRole>
          </ProtectedRoute>
        }
      />
      <Route
        path="/profiles/:key/edit"
        element={
          <ProtectedRoute>
            <RequireRole roles={['admin']}>
              <ProfileEditorPage />
            </RequireRole>
          </ProtectedRoute>
        }
      />
      <Route
        path="/semantic-catalog"
        element={
          <ProtectedRoute>
            <SemanticCatalogPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/evaluation"
        element={
          <ProtectedRoute>
            <EvaluationPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/prompts"
        element={
          <ProtectedRoute>
            <PromptsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/lenses"
        element={
          <ProtectedRoute>
            <LensesPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/simulations"
        element={
          <ProtectedRoute>
            <SimulationsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/calibration"
        element={
          <ProtectedRoute>
            <CalibrationPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/evaluation/:suiteId"
        element={
          <ProtectedRoute>
            <EvaluationSuitePage />
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
