"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const { signIn, signUp } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);

    if (mode === "signup") {
      if (password.length < 6) {
        setError("비밀번호는 6자 이상이어야 합니다.");
        setLoading(false);
        return;
      }
      if (password !== confirmPassword) {
        setError("비밀번호가 일치하지 않습니다.");
        setLoading(false);
        return;
      }
      const { error: err } = await signUp(email, password, displayName);
      if (err) {
        setError(err);
      } else {
        setMessage("가입 완료! 이메일 확인 후 로그인해주세요.");
        setMode("login");
      }
    } else {
      const { error: err } = await signIn(email, password);
      if (err) {
        setError(err);
      } else {
        router.push("/");
      }
    }
    setLoading(false);
  };

  return (
    <div className="fixed inset-0 bg-[#0d1117] flex items-center justify-center z-50">
      <div className="w-full max-w-md p-8">
        <h1 className="text-3xl font-bold text-white text-center mb-1">SEPA Scanner</h1>
        <p className="text-sm text-gray-500 text-center mb-8">v2.0 — React</p>

        <div className="flex gap-1 mb-4">
          <button onClick={() => { setMode("login"); setError(""); }}
            className={`flex-1 py-1.5 rounded text-sm ${mode === "login" ? "bg-blue-600 text-white" : "bg-[#1f2937] text-gray-400"}`}>
            로그인
          </button>
          <button onClick={() => { setMode("signup"); setError(""); }}
            className={`flex-1 py-1.5 rounded text-sm ${mode === "signup" ? "bg-blue-600 text-white" : "bg-[#1f2937] text-gray-400"}`}>
            회원가입
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {mode === "signup" && (
            <input type="text" placeholder="닉네임"
              value={displayName} onChange={(e) => setDisplayName(e.target.value)}
              className="w-full bg-[#161b22] border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-600" />
          )}
          <input type="email" placeholder="이메일" required
            value={email} onChange={(e) => setEmail(e.target.value)}
            className="w-full bg-[#161b22] border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-600" />
          <input type="password" placeholder="비밀번호" required
            value={password} onChange={(e) => setPassword(e.target.value)}
            className="w-full bg-[#161b22] border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-600" />
          {mode === "signup" && (
            <input type="password" placeholder="비밀번호 확인" required
              value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full bg-[#161b22] border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-600" />
          )}
          <button type="submit" disabled={loading}
            className="w-full py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm text-white disabled:opacity-50">
            {loading ? "처리 중..." : mode === "login" ? "로그인" : "가입하기"}
          </button>
        </form>

        {error && <p className="mt-3 text-sm text-red-400 text-center">{error}</p>}
        {message && <p className="mt-3 text-sm text-green-400 text-center">{message}</p>}
      </div>
    </div>
  );
}
