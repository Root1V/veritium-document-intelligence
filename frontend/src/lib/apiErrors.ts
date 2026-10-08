import { isAxiosError } from 'axios'

/** The API's own explanation of a failed request: FastAPI's `detail` is a
 * string, a list of strings (our 400s) or a list of validation errors (422). */
export function errorDetail(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (Array.isArray(detail)) return detail.map((d) => (typeof d === 'string' ? d : d.msg)).join(' · ')
    if (typeof detail === 'string') return detail
  }
  return 'No se pudo completar la operación.'
}
