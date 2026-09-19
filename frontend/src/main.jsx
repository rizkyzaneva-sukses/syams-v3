import React from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter, Routes, Route, Navigate, useOutletContext} from 'react-router-dom';
import Login from './pages/Login';
import MasterControl from './pages/MasterControl';
import OrderDetail from './pages/OrderDetail';
import CMOHome from './pages/CMOHome';
import CustomerList from './pages/CustomerList';
import OrderList from './pages/OrderList';
import POInboxPage from './pages/POInboxPage';
import POIntakeFormPage from './pages/POIntakeFormPage';
import CMOPriorityV2Page from './pages/CMOPriorityV2Page';
import HREmployeeMasterPage from './pages/HREmployeeMasterPage';
import HRRecruitmentPage from './pages/HRRecruitmentPage';
import SampleLifecyclePage from './pages/SampleLifecyclePage';
import SampleTodayPage from './pages/SampleTodayPage';
import SampleTaskPage from './pages/SampleTaskPage';
import PrintingJobCardPage from './pages/PrintingJobCardPage';
import PrintingDailyTargetPage from './pages/PrintingDailyTargetPage';
import CFOReceivablesPage from './pages/CFOReceivablesPage';
import CFOCostingPage from './pages/CFOCostingPage';
import COOExecutionPage from './pages/COOExecutionPage';
import QuotationPage from './pages/QuotationPage';
import SamplePPMPage from './pages/SamplePPMPage';
import SPKPage from './pages/SPKPage';
import ExceptionPage from './pages/ExceptionPage';
import TaskPage from './pages/TaskPage';
import CFOHome from './pages/CFOHome';
import InvoicePage from './pages/InvoicePage';
import PurchaseOrderPage from './pages/PurchaseOrderPage';
import ShipmentListPage from './pages/ShipmentListPage';
import COOHome from './pages/COOHome';
import MaterialRequestPage from './pages/MaterialRequestPage';
import ProductionQueue from './pages/ProductionQueue';
import WIPTracking from './pages/WIPTracking';
import QCRecordPage from './pages/QCRecordPage';
import CEOHome from './pages/CEOHome';
import DecisionPage from './pages/DecisionPage';
import ProductionPlanPage from './pages/ProductionPlanPage';
import DeliveryPage from './pages/DeliveryPage';
import OrderClosingPage from './pages/OrderClosingPage';
import CHROHome from './pages/CHROHome';
import EmployeePage from './pages/EmployeePage';
import TrainingPage from './pages/TrainingPage';
import PerformancePage from './pages/PerformancePage';
import EmployeeIssuePage from './pages/EmployeeIssuePage';
import AuditLogPage from './pages/AuditLogPage';
import BusinessPolicyPage from './pages/BusinessPolicyPage';
import CEOCompanyPerformance from './pages/CEOCompanyPerformance';
import CEOOverride from './pages/CEOOverride';
import BOMCostPage from './pages/BOMCostPage';
import RevisionPage from './pages/RevisionPage';
import CMOPriorityPage from './pages/CMOPriorityPage';
import SalesPipelinePage from './pages/SalesPipelinePage';
import CMOReportsPage from './pages/CMOReportsPage';
import BuyerCRMPage from './pages/BuyerCRMPage';
import SampleApprovalFeedPage from './pages/SampleApprovalFeedPage';
import ReleaseToCOOPage from './pages/ReleaseToCOOPage';
import ExceptionCenterPage from './pages/ExceptionCenterPage';
import DebyTodayPage from './pages/DebyTodayPage';
import AfterSalesPage from './pages/AfterSalesPage';
import GuidePage from './pages/GuidePage';
import PrintingTodayPage from './pages/PrintingTodayPage';
import PurchasingPage from './pages/PurchasingPage';
import Access from './components/Access';
import Layout from './components/Layout';
import {getToken} from './api';
import './styles.css';

function Protected({children}){return getToken()?children:<Navigate to="/login" replace/>}
/* Halaman awal per divisi. Deby (CMO Support) harus mendarat di daftar kerjanya,
   bukan dashboard lintas divisi — itu isi revisi #1. Cecep tetap ke Morning
   Priority miliknya, CHRO ke HR, sisanya ke Master Control. */
const HOME_BY_ROLE={CMO_SUPPORT:'/cmo/today',CMO_MANAGER:'/cmo/priority',CHRO_MANAGER:'/chro',HR_SUPPORT:'/chro'};
function HomeRedirect(){const role=useOutletContext()?.me?.role;return role?<Navigate to={HOME_BY_ROLE[role]||'/master'} replace/>:null}
function App(){return <BrowserRouter><Routes>
  <Route path="/login" element={<Login/>}/>
  <Route path="/" element={<Protected><Layout/></Protected>}>
    <Route index element={<HomeRedirect/>}/>
    <Route path="master" element={<Access><MasterControl/></Access>}/>
    {/* Panduan sengaja tanpa Access: berlaku untuk semua peran */}
    <Route path="panduan" element={<GuidePage/>}/>
    <Route path="orders/:orderId" element={<Access><OrderDetail/></Access>}/>
    {/* CMO */}
    <Route path="cmo" element={<Access><CMOHome/></Access>}/>
    <Route path="cmo/priority" element={<Access><CMOPriorityPage/></Access>}/>
    <Route path="cmo/sales-pipeline" element={<Access><SalesPipelinePage/></Access>}/>
    <Route path="cmo/reports" element={<Access><CMOReportsPage/></Access>}/>
    <Route path="cmo/buyer-crm" element={<Access><BuyerCRMPage/></Access>}/>
    <Route path="cmo/sample-approval" element={<Access><SampleApprovalFeedPage/></Access>}/>
    <Route path="cmo/release-to-coo" element={<Access><ReleaseToCOOPage/></Access>}/>
    <Route path="cmo/exception-center" element={<Access><ExceptionCenterPage/></Access>}/>
    <Route path="cmo/today" element={<Access><DebyTodayPage/></Access>}/>
      <Route path="cmo/priority-v2" element={<Access><CMOPriorityV2Page/></Access>}/>
      <Route path="chro/employees" element={<Access><HREmployeeMasterPage/></Access>}/>
      <Route path="chro/recruitment" element={<Access><HRRecruitmentPage/></Access>}/>
      <Route path="sample/lifecycle" element={<Access><SampleLifecyclePage/></Access>}/>
      <Route path="sample/today" element={<Access><SampleTodayPage/></Access>}/>
      <Route path="sample/tasks" element={<Access><SampleTaskPage/></Access>}/>
      <Route path="printing/job-cards" element={<Access><PrintingJobCardPage/></Access>}/>
      <Route path="printing/daily-target" element={<Access><PrintingDailyTargetPage/></Access>}/>
      <Route path="printing/today" element={<Access><PrintingTodayPage/></Access>}/>
      <Route path="purchasing" element={<Access><PurchasingPage/></Access>}/>
      <Route path="cfo/receivables" element={<Access><CFOReceivablesPage/></Access>}/>
      <Route path="cfo/costing" element={<Access><CFOCostingPage/></Access>}/>
      <Route path="coo/execution" element={<Access><COOExecutionPage/></Access>}/>
    <Route path="cmo/customers" element={<Access><CustomerList/></Access>}/>
    <Route path="cmo/orders" element={<Access><OrderList/></Access>}/>
    <Route path="cmo/orders/new" element={<Navigate to="/cmo/po-inbox/new" replace/>}/>
    <Route path="cmo/po-inbox" element={<Access><POInboxPage/></Access>}/>
    <Route path="cmo/po-inbox/new" element={<Access><POIntakeFormPage/></Access>}/>
    <Route path="cmo/po-inbox/:poId/edit" element={<Access><POIntakeFormPage/></Access>}/>
    <Route path="cmo/quotations" element={<Access><QuotationPage/></Access>}/>
    <Route path="cmo/samples" element={<Access><SamplePPMPage/></Access>}/>
    <Route path="cmo/spk" element={<Access><SPKPage/></Access>}/>
    <Route path="cmo/after-sales" element={<Access><AfterSalesPage/></Access>}/>
    {/* CFO */}
    <Route path="cfo" element={<Access><CFOHome/></Access>}/>
    <Route path="cfo/invoices" element={<Access><InvoicePage/></Access>}/>
    <Route path="cfo/purchase-orders" element={<Access><PurchaseOrderPage/></Access>}/>
    <Route path="cfo/shipments" element={<Access><ShipmentListPage/></Access>}/>
    {/* COO */}
    <Route path="coo" element={<Access><COOHome/></Access>}/>
    <Route path="coo/material-requests" element={<Access><MaterialRequestPage/></Access>}/>
    <Route path="coo/bom-cost" element={<Access><BOMCostPage/></Access>}/>
    <Route path="coo/production" element={<Access><ProductionQueue/></Access>}/>
    <Route path="coo/wip" element={<Access><WIPTracking/></Access>}/>
    <Route path="coo/qc" element={<Access><QCRecordPage/></Access>}/>
    <Route path="coo/planning" element={<Access><ProductionPlanPage/></Access>}/>
    <Route path="coo/deliveries" element={<Access><DeliveryPage/></Access>}/>
    <Route path="coo/closing" element={<Access><OrderClosingPage/></Access>}/>
    {/* CEO */}
    <Route path="ceo" element={<Access><CEOHome/></Access>}/>
    <Route path="ceo/decisions" element={<Access><DecisionPage/></Access>}/>
    <Route path="ceo/business-policy" element={<Access><BusinessPolicyPage/></Access>}/>
    {/* Halaman yang kodenya sudah ada tapi belum pernah dipasang — dipasang
        bersamaan dengan router backend-nya (revisi #70-#78). */}
    <Route path="ceo/company-performance" element={<Access><CEOCompanyPerformance/></Access>}/>
    <Route path="ceo/overrides" element={<Access><CEOOverride/></Access>}/>
    {/* CHRO */}
    <Route path="chro" element={<Access><CHROHome/></Access>}/>
    <Route path="chro/employees" element={<Access><EmployeePage/></Access>}/>
    <Route path="chro/training" element={<Access><TrainingPage/></Access>}/>
    <Route path="chro/performance" element={<Access><PerformancePage/></Access>}/>
    <Route path="chro/issues" element={<Access><EmployeeIssuePage/></Access>}/>
    {/* Common */}
    <Route path="audit-log" element={<Access><AuditLogPage/></Access>}/>
    <Route path="exceptions" element={<Access><ExceptionPage/></Access>}/>
    <Route path="tasks" element={<Access><TaskPage/></Access>}/>
    <Route path="revisions" element={<Access><RevisionPage/></Access>}/>
  </Route>
</Routes></BrowserRouter>}
createRoot(document.getElementById('root')).render(<App/>);
