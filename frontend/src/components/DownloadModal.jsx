import React, { useState } from 'react';
import { Download, ExternalLink, Loader2, Github, X } from 'lucide-react';
import { provisionToGithub } from '../api';

export default function DownloadModal({ 
  isOpen, 
  onClose, 
  requestId, 
  resolvedName, 
  downloadUrl 
}) {
  const [activeTab, setActiveTab] = useState('github');
  
  // Provisioning State
  const [githubOrg, setGithubOrg] = useState('');
  const [repoName, setRepoName] = useState(resolvedName || '');
  const [isProvisioning, setIsProvisioning] = useState(false);
  const [provisionError, setProvisionError] = useState(null);
  const [prUrl, setPrUrl] = useState(null);

  if (!isOpen) return null;

  const handleProvision = async () => {
    setIsProvisioning(true);
    setProvisionError(null);

    try {
      const response = await provisionToGithub(requestId, githubOrg, repoName);
      setPrUrl(response.data.pullRequestUrl);
    } catch (err) {
      const errorMessage = err.response?.data?.error || err.message || 'Failed to provision to GitHub';
      setProvisionError(errorMessage);
    } finally {
      setIsProvisioning(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg overflow-hidden flex flex-col">
        
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center">
          <h2 className="text-lg font-semibold text-gray-800">Retrieve Your Microservice</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={18} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-100 px-6 pt-2">
          <button 
            type="button"
            className={`pb-2 px-4 text-sm font-medium border-b-2 ${
              activeTab === 'github' 
                ? 'border-blue-600 text-blue-600' 
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
            onClick={() => setActiveTab('github')}
          >
            Provision to GitHub (Recommended)
          </button>
          <button 
            type="button"
            className={`pb-2 px-4 text-sm font-medium border-b-2 ${
              activeTab === 'zip' 
                ? 'border-blue-600 text-blue-600' 
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
            onClick={() => setActiveTab('zip')}
          >
            Download ZIP
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 min-h-[250px]">
          
          {/* TAB 1: GitOps Flow */}
          {activeTab === 'github' && (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-gray-600">
                Automatically create a secure, compliant repository with a baseline Pull Request.
              </p>
              
              {!prUrl ? (
                <>
                  <div className="flex flex-col gap-1">
                    <label className="text-sm font-medium text-gray-700">GitHub Organization / Username</label>
                    <input 
                      type="text"
                      className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="e.g., my-company-org"
                      value={githubOrg}
                      onChange={(e) => setGithubOrg(e.target.value)}
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-sm font-medium text-gray-700">Repository Name</label>
                    <input 
                      type="text"
                      className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      value={repoName}
                      onChange={(e) => setRepoName(e.target.value)}
                    />
                  </div>
                  
                  {provisionError && (
                    <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm">
                      {provisionError}
                    </div>
                  )}
                  
                  <button 
                    type="button"
                    className="mt-2 bg-gray-900 text-white font-medium py-2 px-4 rounded hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                    onClick={handleProvision}
                    disabled={!githubOrg || !repoName || isProvisioning}
                  >
                    {isProvisioning ? <Loader2 size={16} className="animate-spin" /> : <Github size={16} />}
                    {isProvisioning ? 'Creating Repository...' : 'Create Repository & PR'}
                  </button>
                </>
              ) : (
                <div className="bg-green-50 border border-green-200 rounded p-4 flex flex-col gap-3">
                  <div className="text-green-800">
                    <strong className="block mb-1">Provisioning Complete! 🚀</strong>
                    <span className="text-sm">Your repository has been created with branch protection enabled.</span>
                  </div>
                  <a 
                    href={prUrl} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="bg-green-600 text-white text-center font-medium py-2 px-4 rounded hover:bg-green-700 flex items-center justify-center gap-2 text-sm"
                  >
                    Review Baseline Pull Request <ExternalLink size={14} />
                  </a>
                </div>
              )}
            </div>
          )}

          {/* TAB 2: Legacy ZIP Download */}
          {activeTab === 'zip' && (
            <div className="flex flex-col gap-6 items-center justify-center pt-4">
              <p className="text-center text-sm text-gray-600">
                Download the raw artifact files locally.<br/>
                <em className="text-gray-500">Note: You will need to manually configure git, branch protection, and CI/CD.</em>
              </p>
              <a 
                href={downloadUrl} 
                download
                className="bg-blue-600 text-white font-medium py-2 px-6 rounded hover:bg-blue-700 flex items-center gap-2"
              >
                <Download size={16} /> Download .ZIP Archive
              </a>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}