import { useEffect } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { ToastProvider } from "@/components/ui";
import { AccountPage } from "@/pages/AccountPage";
import { AdminKycQueuePage } from "@/pages/admin/AdminKycQueuePage";
import { AdminKycReviewPage } from "@/pages/admin/AdminKycReviewPage";
import { AuctionDetailPage } from "@/pages/AuctionDetailPage";
import { AuctionsPage } from "@/pages/AuctionsPage";
import { LoginPage } from "@/pages/auth/LoginPage";
import { RegisterPage } from "@/pages/auth/RegisterPage";
import { LandingPage } from "@/pages/LandingPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { CreateAuctionPage } from "@/pages/seller/CreateAuctionPage";
import { KycPage } from "@/pages/seller/KycPage";
import { SellPage } from "@/pages/seller/SellPage";
import { AuthProvider } from "./auth";
import { RequireAdmin, RequireAuth } from "./guards";
import { LiveProvider } from "./live";

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [pathname]);
  return null;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<LandingPage />} />
        <Route path="login" element={<LoginPage />} />
        <Route path="register" element={<RegisterPage />} />
        <Route path="auctions" element={<AuctionsPage />} />
        <Route path="auctions/:auctionId" element={<AuctionDetailPage />} />
        <Route path="account" element={<RequireAuth><AccountPage /></RequireAuth>} />
        <Route path="sell" element={<RequireAuth><SellPage /></RequireAuth>} />
        <Route path="sell/new" element={<RequireAuth><CreateAuctionPage /></RequireAuth>} />
        <Route path="sell/verify" element={<RequireAuth><KycPage /></RequireAuth>} />
        <Route path="admin/kyc" element={<RequireAdmin><AdminKycQueuePage /></RequireAdmin>} />
        <Route path="admin/kyc/:submissionId" element={<RequireAdmin><AdminKycReviewPage /></RequireAdmin>} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

/** Providers in dependency order; the router lives outside so tests can use a MemoryRouter. */
export function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <LiveProvider>
          <ScrollToTop />
          <AppRoutes />
        </LiveProvider>
      </AuthProvider>
    </ToastProvider>
  );
}
