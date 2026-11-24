/**
 * API client for the IDP backend.
 * Uses Axios with the API Gateway base URL from environment variable.
 */

import axios from 'axios';
import { authEnabled, getAccessToken, login } from './auth';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:3001';

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach the Cognito access token; send the user to login on 401.
if (api.interceptors) {
  api.interceptors.request.use((config) => {
    const token = getAccessToken();
    if (token) config.headers = { ...config.headers, Authorization: `Bearer ${token}` };
    return config;
  });
  api.interceptors.response.use(
    (res) => res,
    (err) => {
      if (authEnabled && err?.response?.status === 401) login();
      return Promise.reject(err);
    },
  );
}

// ─── Policy endpoints ─────────────────────────────────────

export const getPolicy = () => api.get('/policies');
export const updatePolicy = (profile) => api.put('/policies', { profile });
export const getPolicyDefaults = () => api.get('/policies/defaults');

// ─── Request endpoints ────────────────────────────────────

export const createRequest = (serviceRequest) =>
  api.post('/requests', { serviceRequest });

export const listRequests = () => api.get('/requests');

export const getRequestStatus = (id) => api.get(`/requests/${id}/status`);

export const getRequestDetails = (id) => api.get(`/requests/${id}`);

export const getRequestPlan = (id) => api.get(`/requests/${id}/plan`);

export const triggerGeneration = (id, selectedArtifacts) =>
  api.post(`/requests/${id}/generate`, { selectedArtifacts });

// ─── Validation endpoints ─────────────────────────────────

export const getValidation = (id) => api.get(`/requests/${id}/validation`);

// ─── Download endpoints ───────────────────────────────────

export const getDownloadUrl = (id) => api.get(`/requests/${id}/download`);

export default api;
export const provisionToGithub = (id, githubOrg, repositoryName) => 
  api.post(`/requests/${id}/provision`, { githubOrg, repositoryName });
