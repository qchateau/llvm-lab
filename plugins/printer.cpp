#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Passes/PassPlugin.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

namespace {
struct PrintModulePass : public PassInfoMixin<PrintModulePass> {
    PreservedAnalyses run(Module& M, ModuleAnalysisManager&) {
        errs() << "PrintModule running on module: " << M.getName() << "\n";
        return PreservedAnalyses::all();
    }
};

struct PrintFuncPass : public PassInfoMixin<PrintFuncPass> {
    std::string Filter;
    explicit PrintFuncPass(std::string Filter) : Filter(Filter) {}

    PreservedAnalyses run(Function& F, FunctionAnalysisManager&) {
        if (Filter.empty() || F.getName().contains(Filter)) {
            errs() << "Found function: " << F.getName() << "\n";
        }
        return PreservedAnalyses::all();
    }
};
} // end anonymous namespace

extern "C" LLVM_ATTRIBUTE_WEAK PassPluginLibraryInfo llvmGetPassPluginInfo() {
    return {
        LLVM_PLUGIN_API_VERSION, "PrinterPlugin", "v0.1",
        [](PassBuilder& PB) {
            PB.registerPipelineParsingCallback(
                [](StringRef Name, FunctionPassManager& FPM, ArrayRef<PassBuilder::PipelineElement> Args) {
                    if (Name == "print-func") {
                        std::string Filter = "";
                        if (!Args.empty()) {
                           Filter = Args[0].Name.str();
                           if (Filter.size() >= 2 && Filter.front() == '"' && Filter.back() == '"') {
                               Filter = Filter.substr(1, Filter.size() - 2);
                           }
                        }
                        FPM.addPass(PrintFuncPass(Filter));
                        return true;
                    }
                    return false;
                });
            PB.registerPipelineParsingCallback(
                [](StringRef Name, ModulePassManager& MPM, ArrayRef<PassBuilder::PipelineElement>) {
                    if (Name == "print-module") {
                        MPM.addPass(PrintModulePass());
                        return true;
                    }
                    return false;
                });
        }
    };
}
