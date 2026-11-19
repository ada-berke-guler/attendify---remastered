import { useRef, useEffect, useState, useCallback } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import Webcam from 'react-webcam';
import { api } from '../../../shared/api';
import './FaceVerify.css';

const WEBCAM_CONSTRAINTS = {
  width: 640,
  height: 640,
  facingMode: 'user',
};

const DEFAULT_MSG = 'Please hold your phone steady and look directly at the screen.';
const BLINK_MSG   = 'Please blink once to confirm you are real.';

// Convert a base64 data URL to a File object
function dataUrlToFile(dataUrl, filename = 'capture.jpg') {
  const [header, data] = dataUrl.split(',');
  const mime = header.match(/:(.*?);/)[1];
  const bstr = atob(data);
  let n = bstr.length;
  const u8arr = new Uint8Array(n);
  while (n--) u8arr[n] = bstr.charCodeAt(n);
  return new File([u8arr], filename, { type: mime });
}

// Gap between frames. Frames are sent one at a time (next one after the answer), so the
// effective rate is ~2-3 fps: fast enough to catch a slow blink.
const FRAME_GAP_MS = 150;

const REASON_MESSAGES = {
  no_face:          ['error',   'No face detected. Please look directly at the camera.'],
  multiple_faces:   ['error',   'Multiple faces detected. Please make sure only your face is visible.'],
  blur:             ['warning', 'Image too blurry. Hold your phone steady.'],
  no_eye_landmarks: ['warning', 'Cannot detect eyes. Move closer to the camera.'],
  need_blink_close: ['info',    BLINK_MSG],
  need_blink_open:  ['info',    'Now open your eyes…'],
};

export default function FaceVerify() {
  const navigate      = useNavigate();
  const locationState = useLocation();
  const webcamRef     = useRef(null);

  const qrToken = locationState.state?.qr_token ?? null;

  const [permissionDenied, setPermissionDenied] = useState(false);
  const [phase,       setPhase]       = useState('verifying'); // 'verifying' | 'success' | 'stopped'
  const [message,     setMessage]     = useState(DEFAULT_MSG);
  const [messageType, setMessageType] = useState('info');
  const [submitting,  setSubmitting]  = useState(false);

  useEffect(() => {
    if (!qrToken) navigate('/student/scan', { replace: true });
  }, [qrToken, navigate]);

  const show = useCallback((type, text) => { setMessageType(type); setMessage(text); }, []);

  /** Map an API error to a message. Returns the delay before the next frame, or null to stop. */
  const handleError = useCallback((err) => {
    const detail = err.message || '';
    switch (err.status) {
      case 429: {
        const wait = Number(err.retryAfter) || 10;
        show('warning', `Too many attempts. Trying again in ${wait} s…`);
        return wait * 1000;
      }
      case 503:
        show('warning', 'Face service is unavailable. Retrying…');
        return 3000;
      case 400:
        show('error', 'This QR code has expired. Please scan the code on screen again.');
        setTimeout(() => navigate('/student/scan', { replace: true }), 2500);
        return null;
      case 404:
        show('error', 'This attendance session is closed.');
        return null;
      case 409:
        show('warning', 'Attendance already recorded for this session.');
        setTimeout(() => navigate('/student/dashboard'), 2500);
        return null;
      case 403:
        if (detail.includes('not enrolled')) {
          show('error', 'You are not enrolled in this course.');
          return null;
        }
        show('warning', 'Liveness check expired. Please blink again.');
        return 1000;
      case 422:
        if (detail.includes('No face embeddings')) {
          show('error', 'You have not registered your face yet.');
          setTimeout(() => navigate('/student/face-setup'), 2500);
          return null;
        }
        if (detail.includes('distance') || detail.includes('does not match')) {
          show('error', 'Your face does not match this account. Blink again to retry, or ask your instructor.');
          return 3000;
        }
        show('error', detail || 'No face detected. Please look directly at the camera.');
        return 1000;
      default:
        show('error', 'Verification failed. Retrying…');
        return 2000;
    }
  }, [navigate, show]);

  // Blink challenge, then submit the frame that completed it together with the ticket.
  useEffect(() => {
    if (phase !== 'verifying' || permissionDenied || !qrToken) return undefined;
    let cancelled = false;
    let timer;
    const schedule = (ms) => { if (!cancelled) timer = setTimeout(tick, ms); };

    async function tick() {
      const imageSrc = webcamRef.current?.getScreenshot();
      if (!imageSrc) { schedule(300); return; }
      const imageFile = dataUrlToFile(imageSrc, 'capture.jpg');
      try {
        const fd = new FormData();
        fd.append('image', imageFile);
        const result = await api.form('/attendance/liveness-check', fd);
        if (cancelled) return;
        if (!result.is_live) {
          const [type, text] = REASON_MESSAGES[result.reason] ?? ['info', BLINK_MSG];
          show(type, text);
          schedule(FRAME_GAP_MS);
          return;
        }

        show('info', 'Blink detected! Verifying identity…');
        setSubmitting(true);
        const sfd = new FormData();
        sfd.append('qr_token', qrToken);
        sfd.append('liveness_ticket', result.liveness_ticket);
        sfd.append('image', imageFile);
        const data = await api.form('/attendance/submit', sfd);
        if (cancelled) return;

        show('info', 'Identity confirmed!');
        setPhase('success');
        const submittedAt = data.submitted_at ? new Date(data.submitted_at) : new Date();
        const sessionData = {
          ...data,
          date: submittedAt.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }),
          time: submittedAt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }),
          status: data.status ?? 'present',
        };
        setTimeout(() => navigate('/student/confirmation', { state: { session: sessionData } }), 1500);
      } catch (err) {
        if (cancelled) return;
        const next = handleError(err);
        if (next === null) setPhase('stopped');
        else schedule(next);
      } finally {
        if (!cancelled) setSubmitting(false);
      }
    }

    schedule(600); // let the camera settle
    return () => { cancelled = true; clearTimeout(timer); };
  }, [phase, permissionDenied, qrToken, navigate, show, handleError]);

  const verifying = phase === 'verifying' && !permissionDenied;
  const success   = phase === 'success';
  const stopped   = phase === 'stopped';
  const failed    = permissionDenied;

  return (
    <div className="fv-root">
      {/* ── Header ── */}
      <header className="fv-header">
        <button
          type="button"
          className="fv-back-btn"
          onClick={() => navigate('/student/scan')}
          aria-label="Go back"
        >
          <BackArrowIcon />
        </button>
        <h1 className="fv-header-title">Verify Identity</h1>
        <Link to="/student/dashboard" className="fv-cancel-link">Cancel</Link>
      </header>

      {/* ── Body ── */}
      <div className="fv-body">
        <div className="fv-camera-outer" aria-label="Camera viewfinder">
          <div className={`fv-camera-ring${success ? ' fv-ring-success' : failed ? ' fv-ring-failed' : ''}`}>
            {failed ? (
              <div className="fv-cam-denied">
                <CameraOffIcon />
              </div>
            ) : (
              <Webcam
                ref={webcamRef}
                audio={false}
                screenshotFormat="image/jpeg"
                videoConstraints={WEBCAM_CONSTRAINTS}
                className="fv-webcam"
                onUserMediaError={() => setPermissionDenied(true)}
                mirrored
              />
            )}

            {verifying && (
              <div className="fv-face-dots" aria-hidden="true">
                <span className="fv-dot fv-dot-1" />
                <span className="fv-dot fv-dot-2" />
                <span className="fv-dot fv-dot-3" />
                <span className="fv-dot fv-dot-4" />
                <span className="fv-dot fv-dot-5" />
              </div>
            )}

            {success && (
              <div className="fv-overlay fv-overlay-success" aria-hidden="true">
                <div className="fv-overlay-badge fv-overlay-badge-success">
                  <CheckLgIcon />
                </div>
              </div>
            )}
          </div>

          <svg
            className={`fv-arc-svg${verifying ? ' fv-arc-spin' : ''}`}
            width="240"
            height="240"
            viewBox="0 0 240 240"
            fill="none"
            aria-hidden="true"
          >
            <circle cx="120" cy="120" r="112" stroke="#bfdbfe" strokeWidth="3" fill="none" />
            {verifying && (
              <circle
                cx="120" cy="120" r="112"
                stroke="#2563eb"
                strokeWidth="3"
                strokeLinecap="round"
                strokeDasharray="80 480"
                fill="none"
              />
            )}
            {success && (
              <circle cx="120" cy="120" r="112" stroke="#86efac" strokeWidth="3" fill="none" />
            )}
          </svg>

          {verifying && (
            <div className="fv-cam-btn" aria-hidden="true">
              <SmallCameraIcon />
            </div>
          )}
        </div>

        {/* ── Text ── */}
        <h2 className="fv-title">
          {success ? 'Identity Confirmed' : failed ? 'Verification Failed' : 'Face Verification'}
        </h2>

        {(verifying || stopped) && (
          <div className={`fv-alert fv-alert-${messageType}`} role="status" aria-live="polite">
            {messageType === 'error'   && <span className="fv-alert-icon">✕</span>}
            {messageType === 'warning' && <span className="fv-alert-icon">!</span>}
            {messageType === 'info'    && <span className="fv-alert-icon">i</span>}
            <span>{message}</span>
          </div>
        )}

        {(success || failed) && (
          <p className="fv-subtitle">
            {success ? message : 'Camera access denied.'}
          </p>
        )}

        {verifying && (
          <div className="fv-status-pill" role="status" aria-live="polite">
            <span className="fv-status-dot" aria-hidden="true" />
            {submitting ? 'Submitting…' : 'Verifying...'}
          </div>
        )}

        {stopped && (
          <button type="button" className="fv-continue-btn" onClick={() => navigate('/student/dashboard')}>
            Back to dashboard
          </button>
        )}
      </div>

      <footer className="fv-footer">
        <div className="fv-encrypted">
          <LockIcon />
          <span>ENCRYPTED &amp; SECURE</span>
        </div>
        <p className="fv-privacy-text">
          Your biometric data is processed securely and is never shared with third parties.
        </p>
      </footer>
    </div>
  );
}

/* ── Icons ── */
function BackArrowIcon() { return (<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6" /></svg>); }
function SmallCameraIcon() { return (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" /><circle cx="12" cy="13" r="4" /></svg>); }
function CheckLgIcon() { return (<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>); }
function LockIcon() { return (<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>); }
function CameraOffIcon() { return (<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><line x1="1" y1="1" x2="23" y2="23" /><path d="M21 21H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3m3-3h6l2 3h2.5" /><circle cx="12" cy="13" r="3" /></svg>); }