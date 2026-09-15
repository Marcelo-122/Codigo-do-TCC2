#include <opencv2/opencv.hpp>
#include <iostream>
#include <filesystem>
#include <string>
#include <vector>
#include <sstream>
#include <fstream>

using namespace std;
namespace fs = std::filesystem;

void print_dados_imagem(std::stringstream &ss, cv::Mat imagem, auto tamanho_kb){
    ss << "Largura: " << imagem.cols << " px" << std::endl;
    ss << "Altura: " << imagem.rows << " px" << std::endl;
    ss << "Canais de Cor: " << imagem.channels() << std::endl;
    ss << "Tamanho: " << tamanho_kb << " bytes" << std::endl;
}

int main() {
    std::vector<std::string> caminhos_processamento_imagens;
    std::string caminho_input_imagens = "imagens";
    cv::Mat imagem_original, imagem_cinza, imagem_binaria;
    std::vector<uchar> buffer;
    std::stringstream ss;
    std::string 
        output_paste = "output/",
        output_file_path;

    if(fs::exists(caminho_input_imagens) && fs::is_directory(caminho_input_imagens)){
        for(auto& file : fs::directory_iterator(caminho_input_imagens)){
            std::string extension = file.path().extension().string();
            if(extension == ".jpg" || extension == ".png")
                caminhos_processamento_imagens.push_back(file.path().string());
        }
    }

    for(auto&arquivo : caminhos_processamento_imagens){
        fs::path file_path = arquivo;
        std::string nm_arquivo = file_path.filename().string();

        ss << std::string(5,'=') << " " << nm_arquivo << " " << std::string(5,'=') <<  std::endl;
        imagem_original = cv::imread(arquivo);
        
        if(imagem_original.empty()){
            std::cerr << "[ERRO] Falha ao tentar importar imagem! " << arquivo;
            return EXIT_FAILURE;
        }
        for(int i = 0; i < 100; i += 10){
            std::vector<int> params;
            params.push_back(cv::IMWRITE_JPEG_QUALITY);
            params.push_back(i); // Nível máximo de compressão
    
            ss << std::string(5,'*') << " PARÂMETROS " << std::string(5,'*') << std::endl;
            ss << "Algoritmo: JPG" << std::endl;
            ss << "Qualidade: " << i << std::endl;
            ss << std::string(10,'*') << std::endl;
    
            ss << std::string(5,'-')<< " Imagem Original " << std::string(5,'-') << std::endl;
            cv::imencode(".jpg", imagem_original, buffer, params);
            output_file_path = output_paste + nm_arquivo + "_" + "original_qualidade" + "_" + std::to_string(i) + "_" + ".jpg"; 
            cv::imwrite(output_file_path, imagem_original, params);
            print_dados_imagem(ss,imagem_original, buffer.size());
            ss << std::string(10 + nm_arquivo.size(),'-') << std::endl;
            
            cv::cvtColor(imagem_original, imagem_cinza, cv::COLOR_BGR2GRAY);
            ss << std::string(5,'-')<< " Imagem Escala Cinza " << std::string(5,'-') << std::endl;
            output_file_path = output_paste + nm_arquivo + "_" + "escala_cinza_qualidade" + "_" + std::to_string(i) + "_" + ".jpg"; 
            cv::imwrite(output_file_path, imagem_cinza, params);
            cv::imencode(".jpg", imagem_cinza, buffer, params);
            print_dados_imagem(ss,imagem_cinza, buffer.size());
            ss << std::string(10 + nm_arquivo.size(),'-') << std::endl;
            
            cv::threshold(imagem_cinza, imagem_binaria, 0, 255, cv::THRESH_BINARY | cv::THRESH_OTSU);
            ss << std::string(5,'-')<< " Imagem Binarizada " << std::string(5,'-') << std::endl;
            output_file_path = output_paste + nm_arquivo + "_" + "binarizada_qualidade" + "_" + std::to_string(i) + "_" + ".jpg"; 
            cv::imwrite(output_file_path, imagem_binaria, params);
            cv::imencode(".jpg", imagem_binaria, buffer, params);
            print_dados_imagem(ss,imagem_binaria, buffer.size());
            ss << std::string(10 + nm_arquivo.size(),'-') << std::endl;           
        }
        ss << std::string(10 + nm_arquivo.size(),'=') << std::endl;
    }

    std::ofstream output("output.txt");
    if(output.is_open()){
        output << ss.str();
        output.close();
    }
    cv::waitKey(0);
    return EXIT_SUCCESS;
}