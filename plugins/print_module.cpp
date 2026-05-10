#include <llvm/Passes/PassBuilder.h>
#include <llvm/Passes/PassPlugin.h>
#include <llvm/Support/raw_ostream.h>

using namespace llvm;

namespace {
struct PrintModule : public PassInfoMixin<PrintModule> {
    PreservedAnalyses run(Module& M, ModuleAnalysisManager&)
    {
        errs() << "PrintModule running on module: " << M.getName() << "\n";
        return PreservedAnalyses::all();
    }
};
} // end anonymous namespace

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo llvmGetPassPluginInfo()
{
    return {
        LLVM_PLUGIN_API_VERSION,
        "PrintModule",
        "v0.1",
        [](PassBuilder& PB) {
            PB.registerPipelineStartEPCallback(
                [](ModulePassManager& MPM, OptimizationLevel Level) {
                    MPM.addPass(PrintModule());
                });
        },
    };
}
