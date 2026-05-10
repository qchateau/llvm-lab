#include <llvm/Passes/PassBuilder.h>
#include <llvm/Passes/PassPlugin.h>
#include <llvm/Support/raw_ostream.h>

using namespace llvm;

namespace {
struct ExamplePass : public PassInfoMixin<ExamplePass> {
    PreservedAnalyses run(Module& M, ModuleAnalysisManager&)
    {
        errs() << "ExamplePass running on module: " << M.getName() << "\n";
        return PreservedAnalyses::all();
    }
};
} // end anonymous namespace

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo llvmGetPassPluginInfo()
{
    return {
        LLVM_PLUGIN_API_VERSION,
        "ExamplePlugin",
        "v0.1",
        [](PassBuilder& PB) {
            PB.registerPipelineStartEPCallback(
                [](ModulePassManager& MPM, OptimizationLevel Level) {
                    MPM.addPass(ExamplePass());
                });
        },
    };
}
